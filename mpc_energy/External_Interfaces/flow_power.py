from datetime import datetime, timedelta
from amber_api import PriceForecast, amber_data
from mpc_logger import logger
import math


class FlowPowerInterface:
    """
    Price provider adapter that mimics the AmberAPI interface using HA entities.
    """

    def __init__(self, ha, import_price_entity_id, export_price_entity_id, price_forecast_entity_id):
        self.ha = ha
        self.import_price_entity_id = import_price_entity_id
        self.export_price_entity_id = export_price_entity_id
        self.price_forecast_entity_id = price_forecast_entity_id

        self.happy_hour_off_rate = 0.0  # Default off-peak rate in c/kWh when happy hour metadata is used.

        logger.error("Demand pricing not yet supported in Flow Power mode.")
        self.demand_tarrif = False
        self.demand_tarrif_price = None

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
                price = current_price
            else:
                price = forecast_30min[interval_index].price

            values.append(round(price))
        
        values[0] = round(current_price)  # Ensure first value reflects current price for MPC stability.
        return values

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

        # Prefer dedicated forecast entities when available. Fall back to the combined
        # forecast sensor if import/export entities don't include forecast metadata.
        import_points = self._extract_forecast_points(import_payload)
        if not import_points:
            import_points = self._extract_forecast_points(forecast_payload)

        export_points = self._extract_forecast_points(export_payload)

        if forecast_hrs is None:
            forecast_hrs = 24

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
        demand_window_extrapolated_forecast = [False] * intervals_5m

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