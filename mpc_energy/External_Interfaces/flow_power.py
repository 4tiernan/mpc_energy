from datetime import datetime, time as datetime_time, timezone, timedelta
from amber_api import PriceForecast, amber_data
from mpc_logger import logger
import math


class FlowPowerInterface:
    """
    Price provider adapter that mimics the AmberAPI interface using HA entities.
    """

    def __init__(self, ha, import_price_entity_id, export_price_entity_id, price_forecast_entity_id, demand_tarrif_price=None, demand_tarrif_window_start=None, demand_tarrif_window_end=None):
        self.ha = ha
        self.import_price_entity_id = import_price_entity_id
        self.export_price_entity_id = export_price_entity_id
        self.price_forecast_entity_id = price_forecast_entity_id

        self.happy_hour_off_rate = 0.0  # Default off-peak rate in c/kWh when happy hour metadata is used.

        self.demand_tarrif_price = None
        self.demand_tarrif_window_start = None
        self.demand_tarrif_window_end = None

        if(demand_tarrif_price is not None):
            if(demand_tarrif_price == ""):
                logger.warning("Demand price is blank. Demand tarrif will be disabled.")
                self.demand_tarrif = False
            else:
                try:
                    self.demand_tarrif_price = float(demand_tarrif_price) # $/kW
                    self.demand_tarrif_window_start = demand_tarrif_window_start
                    self.demand_tarrif_window_end = demand_tarrif_window_end
                    self.demand_tarrif = True
                    logger.info(f"Demand tarrif enabled at ${self.demand_tarrif_price}/kW from {self.demand_tarrif_window_start} to {self.demand_tarrif_window_end}.")
                except Exception as e:
                    logger.error(f"Invalid demand price '{demand_tarrif_price}'. Demand tarrif will be disabled. Error: {e}")
                    self.demand_tarrif = False

        if self.import_price_entity_id == "" or self.export_price_entity_id == "" or self.price_forecast_entity_id == "":
            raise ValueError(
                "Flow Power mode selected but one or more Flow Power entity IDs are blank. "
                "Please set all required Flow Power entity IDs."
            ) from None

    def _get_state_payload(self, entity_id):
        state_payload = self.ha.get_state(entity_id)
        return state_payload

    def _state_to_cents_per_kwh(self, state_payload, entity_id):
        state = state_payload.get("state")
        attributes = state_payload.get("attributes", {})
        unit = attributes.get("unit") or attributes.get("unit_of_measurement")

        try:
            value = float(state)
        except Exception as e:
            raise ValueError(
                f"Unable to convert state '{state}' for entity '{entity_id}' to float. "
                "Please check the entity returns a numeric value."
            ) from e

        if unit == "$/kWh":
            return value * 100.0

        return value

    def _parse_forecast_timestamp(self, ts):
        # Flow Power exposes timestamps like: 2026-03-29 22:00:00+1000
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S%z")
        return dt.astimezone(self.ha.local_tz)

    def _extract_forecast_points(self, state_payload):
        attributes = state_payload.get("attributes", {})
        #logger.debug(f"Extracting forecast points from attributes: {attributes}")

        forecast_dict = attributes.get("forecast_dict")
        if isinstance(forecast_dict, dict) and forecast_dict:
            return list(forecast_dict.items())

        timestamps = attributes.get("timestamps", [])
        forecast = attributes.get("forecast", [])
        if timestamps and forecast:
            return list(zip(timestamps, forecast))

        return []

    def _build_forecast(self, points, default_price_cents, periods=None, period_minutes=30):
        now = datetime.now(self.ha.local_tz).replace(second=0, microsecond=0)

        parsed = []
        for ts, price in points:
            try:
                start = self._parse_forecast_timestamp(ts)
                parsed.append((start, float(price) * 100.0))  # $/kWh -> c/kWh
            except Exception:
                continue

        parsed.sort(key=lambda x: x[0])
        parsed = [p for p in parsed if p[0] + timedelta(minutes=period_minutes) > now]

        intervals = []
        selected_points = parsed if periods is None else parsed[:periods]
        for start, cents in selected_points:
            end = start + timedelta(minutes=period_minutes)
            intervals.append(
                PriceForecast(price=cents, start_time=start, end_time=end, demand_window=False)
            )

        if not intervals:
            # Fallback to flat forecast if no forecast data was available/parsible.
            for i in range(periods):
                start = now + timedelta(minutes=i * period_minutes)
                end = start + timedelta(minutes=period_minutes)
                intervals.append(
                    PriceForecast(price=default_price_cents, start_time=start, end_time=end, demand_window=False)
                )

        return intervals

    def _build_demand_window_5min(self, intervals_5m, timeline_start):
        if not self.demand_tarrif or not self.demand_tarrif_window_start or not self.demand_tarrif_window_end:
            return [False] * intervals_5m

        try:
            sh, sm = [int(x) for x in str(self.demand_tarrif_window_start).split(":")[:2]]
            eh, em = [int(x) for x in str(self.demand_tarrif_window_end).split(":")[:2]]
        except Exception:
            logger.warning("Invalid demand window format; disabling demand window forecast.")
            return [False] * intervals_5m

        start_min = sh * 60 + sm
        end_min = eh * 60 + em

        out = []
        ts = timeline_start.replace(second=0, microsecond=0)

        for i in range(intervals_5m):
            t = ts + timedelta(minutes=5 * i)
            m = t.hour * 60 + t.minute

            if start_min < end_min:
                in_window = start_min <= m < end_min
            elif start_min > end_min:
                in_window = (m >= start_min) or (m < end_min)  # overnight
            else:
                in_window = True  # 24h window if equal times

            out.append(in_window)

        return out

    def _extend_export_forecast_with_schedule(self, forecast_30min, export_payload, default_price_cents, required_30min_periods):
        """
        Extend export forecast using Flow Power happy-hour attributes when the
        payload forecast horizon is shorter than the requested MPC horizon.
        """
        if len(forecast_30min) >= required_30min_periods:
            return forecast_30min[:required_30min_periods]

        attributes = export_payload.get("attributes", {})
        happy_hour_start = attributes.get("happy_hour_start")
        happy_hour_end = attributes.get("happy_hour_end")
        happy_hour_rate = attributes.get("happy_hour_rate")

        if not happy_hour_start or not happy_hour_end or happy_hour_rate is None:
            return forecast_30min

        try:
            start_hh, start_mm = [int(x) for x in str(happy_hour_start).split(":")[:2]]
            end_hh, end_mm = [int(x) for x in str(happy_hour_end).split(":")[:2]]
            happy_rate_cents = float(happy_hour_rate) * 100.0  # $/kWh -> c/kWh
        except Exception:
            return forecast_30min

        # Build minute-of-day window boundaries.
        happy_start_min = start_hh * 60 + start_mm
        happy_end_min = end_hh * 60 + end_mm

        if forecast_30min:
            next_start = forecast_30min[-1].end_time
            extended = list(forecast_30min)
        else:
            next_start = datetime.now(self.ha.local_tz).replace(second=0, microsecond=0)
            extended = []

        while len(extended) < required_30min_periods:
            minute_of_day = next_start.hour * 60 + next_start.minute

            in_happy_hour = False
            if happy_start_min < happy_end_min:
                in_happy_hour = happy_start_min <= minute_of_day < happy_end_min
            elif happy_start_min > happy_end_min:
                # Overnight window support.
                in_happy_hour = minute_of_day >= happy_start_min or minute_of_day < happy_end_min

            price_cents = happy_rate_cents if in_happy_hour else default_price_cents
            end = next_start + timedelta(minutes=30)
            extended.append(
                PriceForecast(price=price_cents, start_time=next_start, end_time=end, demand_window=False)
            )
            next_start = end

        return extended[:required_30min_periods]

    def _forecast_to_5min(self, forecast_30min, intervals_5m, timeline_start, current_price):
        """
        Convert 30-minute forecast intervals into 5-minute values aligned to the
        MPC timeline start. This prevents time-shift when the first forecast
        interval starts after the current 5-minute slot.
        """
        if intervals_5m <= 0:
            return []

        if not forecast_30min:
            return [round(current_price)] * intervals_5m

        timeline_start = timeline_start.replace(second=0, microsecond=0)
        values = []
        interval_index = 0

        for step in range(intervals_5m):
            t = timeline_start + timedelta(minutes=5 * step)

            # Advance interval pointer while forecast intervals end before t.
            while interval_index + 1 < len(forecast_30min) and t >= forecast_30min[interval_index].end_time:
                interval_index += 1

            if t < forecast_30min[0].start_time:
                price = forecast_30min[0].price
            else:
                price = forecast_30min[interval_index].price

            values.append(round(price))
        
        return values
    
    def create_fake_forecast(self, extrapolated_general_forecast, sim_start, sim_end):
        '''Create a fake forecast that reflects reality more closely than the provided flow power forecast. The fake forecast is overridden with the flow power forecast when the flow power forecast is higher.'''
        fake_forecast = []
        current_time = sim_start
        forecast_index = 0

        while current_time < sim_end:
            current_clock_time = current_time.time()
            if datetime_time(10, 0) <= current_clock_time < datetime_time(14, 0):
                base_price = 15
            elif datetime_time(7, 0) <= current_clock_time < datetime_time(10, 0):
                base_price = 25
            elif datetime_time(14, 0) <= current_clock_time < datetime_time(16, 0):
                base_price = 25
            elif datetime_time(16, 0) <= current_clock_time < datetime_time(21, 0):
                base_price = 55
            else:
                base_price = 35
            
            '''
            if forecast_index < len(extrapolated_general_forecast) and (current_time - sim_start) < timedelta(hours=12): # Only modify the forecast if its within the known forecast horizon
                fake_forecast.append(max(base_price, extrapolated_general_forecast[forecast_index]))
            else:'''
            
            fake_forecast.append(base_price)

            forecast_index += 1
            current_time += timedelta(minutes=5)

        return fake_forecast
    
    def get_data(self, partial_update=False, forecast_hrs=None, sim_start=None, sim_end=None):
        import_payload = self._get_state_payload(self.import_price_entity_id)
        export_payload = self._get_state_payload(self.export_price_entity_id)
        forecast_payload = self._get_state_payload(self.price_forecast_entity_id)

        general_price = self._state_to_cents_per_kwh(import_payload, self.import_price_entity_id)
        feed_in_price = self._state_to_cents_per_kwh(export_payload, self.export_price_entity_id)

        if feed_in_price < -1000:
            logger.warning(
                "Flow feed-in price appears unexpectedly low. "
                "Confirm the entity units are in c/kWh."
            )


        import_points = self._extract_forecast_points(forecast_payload)

        import_points = [(ts, val * 1.5) for ts, val in import_points] # Inflate import forecast by 50% to better reflect PEA affect

        export_points = self._extract_forecast_points(export_payload)

        if forecast_hrs is None:
            forecast_hrs = 24
            logger.warning("No forecast horizon provided; defaulting to 24 hours.")

        if sim_start is not None and sim_end is not None and sim_end > sim_start:
            forecast_minutes = (sim_end - sim_start).total_seconds() / 60.0
            intervals_5m = max(int(math.ceil(forecast_minutes / 5.0)), 1)
        else:
            intervals_5m = max(int(math.ceil(forecast_hrs * 12)), 1)

        required_30min_periods = max(int(math.ceil(intervals_5m / 6.0)), 1)

        # Build full-horizon forecasts for MPC extrapolation so export happy-hour
        # windows are consumed programmatically from HA forecast metadata.
        general_price_forecast_full = self._build_forecast(import_points, default_price_cents=general_price, periods=required_30min_periods, period_minutes=30)
        feed_in_price_forecast_full = self._build_forecast(export_points, default_price_cents=feed_in_price, periods=required_30min_periods, period_minutes=30)
        feed_in_price_forecast_full = self._extend_export_forecast_with_schedule(
            forecast_30min=feed_in_price_forecast_full,
            export_payload=export_payload,
            default_price_cents=self.happy_hour_off_rate,
            required_30min_periods=required_30min_periods,
        )

        # Keep legacy 12hr fields populated with 24 x 30-minute points.
        general_price_forecast = general_price_forecast_full[:24]
        feed_in_price_forecast = feed_in_price_forecast_full[:24]

        sorted_general_forecast = sorted(general_price_forecast, key=lambda x: x.price, reverse=True)
        sorted_feed_in_forecast = sorted(feed_in_price_forecast, key=lambda x: x.price, reverse=True)

        timeline_start = sim_start if sim_start is not None else datetime.now(self.ha.local_tz)
        timeline_start = timeline_start.replace(second=0, microsecond=0)

        general_extrapolated_forecast = self._forecast_to_5min(
            general_price_forecast_full,
            intervals_5m,
            timeline_start=timeline_start,
            current_price=general_price,
        )

        feed_in_extrapolated_forecast = self._forecast_to_5min(
            feed_in_price_forecast_full,
            intervals_5m,
            timeline_start=timeline_start,
            current_price=feed_in_price,
        )

        demand_window_extrapolated_forecast = self._build_demand_window_5min(
            intervals_5m=intervals_5m,
            timeline_start=timeline_start,
        )

        #fake_general_forecast = self.create_fake_forecast(general_extrapolated_forecast, sim_start, sim_end)
        #logger.warning("Using fake prices for flow power general forecast to better reflect daily price patterns.")

        # Set the import price to be at least 10c higher than the export price to reflect reality
        for i, import_price in enumerate(general_extrapolated_forecast):
            export_price = feed_in_extrapolated_forecast[i] if i < len(feed_in_extrapolated_forecast) else feed_in_price
            if(import_price < export_price):
                general_extrapolated_forecast[i] = export_price + 10

        self.data = amber_data(
            demand_tarrif_price=self.demand_tarrif_price,
            general_price=round(general_price),
            feedIn_price=round(feed_in_price),
            prices_estimated=False,
            general_max_forecast_price=round(sorted_general_forecast[0].price),
            feedIn_max_forecast_price=round(sorted_feed_in_forecast[0].price),
            general_12hr_forecast=general_price_forecast,
            feedIn_12hr_forecast=feed_in_price_forecast,
            general_12hr_forecast_sorted=sorted_general_forecast,
            feedIn_12hr_forecast_sorted=sorted_feed_in_forecast,
            general_extrapolated_forecast=general_extrapolated_forecast,
            feedIn_extrapolated_forecast=feed_in_extrapolated_forecast,
            demand_window_extrapolated_forecast=demand_window_extrapolated_forecast,
        )
        return self.data