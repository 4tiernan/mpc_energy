from datetime import datetime, timedelta
from External_Interfaces.amber_api import PriceForecast, price_data
from mpc_logger import logger
import math
import data_helpers
from collections import defaultdict
from exceptions import FlowPowerError


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
            raise FlowPowerError(
                "Flow Power mode selected but one or more Flow Power entity IDs are blank. "
                "Please set all required Flow Power entity IDs."
                f"Provided import price entity ID: '{self.import_price_entity_id}', export price entity ID: '{self.export_price_entity_id}', price forecast entity ID: '{self.price_forecast_entity_id}'."
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
            raise FlowPowerError(
                f"Unable to convert state '{state}' for entity '{entity_id}' to float. "
                "Please check the entity returns a numeric value."
            ) from e

        if unit == "$/kWh":
            return value * 100.0

        return value

    def _parse_forecast_timestamp(self, ts):
        """
        Parse various timestamp formats returned by Flow Power export attributes.
        Supported formats:
        - ISO 8601 with 'T' and colon timezone: 2026-08-10T16:00:00+10:00
        - Legacy format with space and no colon in offset: 2026-03-29 22:00:00+1000
        """
        # Try ISO 8601 first (handles 'T' and '+10:00')
        try:
            # datetime.fromisoformat handles offsets like +10:00
            dt = datetime.fromisoformat(ts)
            return dt.astimezone(self.ha.local_tz)
        except Exception:
            logger.debug(f"Failed to parse timestamp '{ts}' as ISO 8601. Trying legacy format.")
            pass

        # Try legacy format with space and no colon in offset
        try:
            dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S%z")
            return dt.astimezone(self.ha.local_tz)
        except Exception:
            pass

        # Try to normalize offsets like +1000 -> +10:00 and parse again
        try:
            if ts and (ts[-5] in ['+', '-'] and ts[-3] != ':'):
                # Insert colon before last two digits of offset
                ts2 = ts[:-2] + ":" + ts[-2:]
                dt = datetime.fromisoformat(ts2)
                return dt.astimezone(self.ha.local_tz)
        except Exception:
            pass

        raise FlowPowerError(f"Unrecognized timestamp format from Flow export attributes: {ts}")

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

        logger.warning("No forecast data found in Flow Power attributes. Returning empty forecast.")
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
            logger.warning(f"No valid forecast intervals found; using flat forecast with default price of {default_price_cents} c/kWh")
            for i in range(periods):
                start = now + timedelta(minutes=i * period_minutes)
                end = start + timedelta(minutes=period_minutes)
                intervals.append(
                    PriceForecast(price=default_price_cents, start_time=start, end_time=end, demand_window=False)
                )

        return intervals

    def _project_buy_price_from_history(self, import_points):
        """
        Project future buy prices using a time-of-day profile averaged from the 
        last 3 days of history to fill gaps beyond the provided forecast.
        """
        now = datetime.now(self.ha.local_tz).replace(second=0, microsecond=0)
        hist_start = now - timedelta(days=3)
        
        try:
            history = self.ha.get_history(self.import_price_entity_id, start_time=hist_start, end_time=now)
            if not history:
                return import_points

            state_payload = self.ha.get_state(self.import_price_entity_id)
            attributes = state_payload.get("attributes", {})
            unit = attributes.get("unit") or attributes.get("unit_of_measurement")
            scale_to_dollars = 0.01 if unit == "c/kWh" else 1.0

            # 1. Bin history to 5-minute resolution and group into 30-minute TOD buckets to get true averages.
            binned_5m = data_helpers.bin_data(history, 5, hist_start, now, interpolation_method="step")
            tod_bins = defaultdict(list)
            for b in binned_5m:
                if b.avg_state is None:
                    continue
                try:
                    val = float(b.avg_state) * scale_to_dollars  # $/kWh
                    # Snap the 5-minute reading to the start of its 30-minute block for averaging
                    t_rounded = b.time.replace(second=0, microsecond=0)
                    t_rounded -= timedelta(minutes=t_rounded.minute % 30)
                    tod_bins[t_rounded.time()].append(val)
                except: continue
            
            profile = {tod: sum(vals)/len(vals) for tod, vals in tod_bins.items()}
            if not profile:
                logger.warning("No valid historical data found for Flow Power import price; using default average of 0.45 $/kWh.")
                global_avg = 0.45 #Default avg import price if no history is available
            else:
                global_avg = sum(profile.values()) / len(profile)

            # 2. Initialize a 72h grid (30-min steps) with the profile values.
            horizon_start = now - timedelta(minutes=now.minute % 30)
            projected_points = {}
            for i in range(145): # 72 hours at 30 min intervals
                ts = horizon_start + timedelta(minutes=i * 30)
                if ts + timedelta(minutes=30) < now: continue
                
                ts_str = ts.isoformat(timespec="seconds")
                projected_points[ts_str] = profile.get(ts.time(), global_avg)

            # 3. Overlay actual forecast points.
            for ts_str, val in import_points:
                projected_points[ts_str] = val

            final_points = list(projected_points.items())
            logger.debug(f"Buy price projection: {len(final_points)} grid points generated (History profile + {len(import_points)} forecast points).")
            return final_points
        except Exception as e:
            logger.warning(f"Failed to project Flow Power buy price from history: {e}")
            return import_points

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

    def _project_export_price_from_history(self, export_payload, forecast_start, required_30min_periods):
        """Repeat the previous full day's raw export prices over the forecast horizon."""
        previous_day_start = forecast_start.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        previous_day_end = previous_day_start + timedelta(days=1)

        try:
            history = self.ha.get_history(
                self.export_price_entity_id,
                start_time=previous_day_start,
                end_time=previous_day_end,
            )
            history = sorted(
                (item for item in history if item.state is not None),
                key=lambda item: item.time,
            )
            if not history:
                message = (
                    f"No complete-day history found for Flow Power export price entity "
                    f"'{self.export_price_entity_id}' between {previous_day_start} and {previous_day_end}."
                )
                logger.error(message)
                raise FlowPowerError(message)

            unit = export_payload.get("attributes", {}).get("unit") or export_payload.get("attributes", {}).get("unit_of_measurement")
            scale_to_cents = 100.0 if unit == "$/kWh" else 1.0
            source_intervals = []
            for index, item in enumerate(history):
                start = item.time.astimezone(self.ha.local_tz)
                if index + 1 < len(history):
                    end = history[index + 1].time.astimezone(self.ha.local_tz)
                else:
                    end = start + timedelta(minutes=30)
                if end <= start:
                    continue
                source_intervals.append((start.time(), end - start, float(item.state) * scale_to_cents))

            if not source_intervals:
                message = (
                    f"No valid historical export price intervals found for Flow Power entity "
                    f"'{self.export_price_entity_id}'."
                )
                logger.error(message)
                raise FlowPowerError(message)

            forecast_end = forecast_start + timedelta(minutes=required_30min_periods * 30)
            forecast_day_start = forecast_start.replace(hour=0, minute=0, second=0, microsecond=0)
            projected = []
            for day_offset in range(4):
                day = forecast_day_start + timedelta(days=day_offset)
                for start_time, duration, price in source_intervals:
                    start = day.replace(
                        hour=start_time.hour,
                        minute=start_time.minute,
                        second=start_time.second,
                        microsecond=start_time.microsecond,
                    )
                    end = start + duration
                    if end > forecast_start and start < forecast_end:
                        projected.append(
                            PriceForecast(price=price, start_time=start, end_time=end, demand_window=False)
                        )

            projected.sort(key=lambda interval: interval.start_time)
            return projected
        except Exception as e:
            if isinstance(e, FlowPowerError):
                raise
            logger.error(f"Failed to project Flow Power export price from history: {e}")
            raise FlowPowerError(
                f"Failed to project Flow Power export price from history for entity "
                f"'{self.export_price_entity_id}'."
            ) from e

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


        import_points = self._extract_forecast_points(forecast_payload)

        #import_points = [(ts, val * 1.5) for ts, val in import_points] # Inflate import forecast by 50% to better reflect PEA affect

        if forecast_hrs is None:
            forecast_hrs = 24
            logger.warning("No forecast horizon provided; defaulting to 24 hours.")

        if sim_start is not None and sim_end is not None and sim_end > sim_start:
            forecast_minutes = (sim_end - sim_start).total_seconds() / 60.0
            intervals_5m = max(int(math.ceil(forecast_minutes / 5.0)), 1)
        else:
            intervals_5m = max(int(math.ceil(forecast_hrs * 12)), 1)

        required_30min_periods = max(int(math.ceil(intervals_5m / 6.0)), 1)

        timeline_start = sim_start if sim_start is not None else datetime.now(self.ha.local_tz)
        timeline_start = timeline_start.replace(second=0, microsecond=0)

        # Build full-horizon forecasts for MPC extrapolation.
        import_points_projected = self._project_buy_price_from_history(import_points)
        
        general_price_forecast_full = self._build_forecast(import_points_projected, default_price_cents=35.0, periods=required_30min_periods, period_minutes=30)
        feed_in_price_forecast_full = self._project_export_price_from_history(
            export_payload=export_payload,
            forecast_start=timeline_start,
            required_30min_periods=required_30min_periods,
        )
        general_price_forecast = general_price_forecast_full[:24]
        feed_in_price_forecast = feed_in_price_forecast_full[:24]

        general_max_price = max((pf.price for pf in general_price_forecast[:24]), default=0)
        feed_in_max_price = max((pf.price for pf in feed_in_price_forecast[:24]), default=0)

        general_extrapolated_forecast = self._forecast_to_5min(
            general_price_forecast_full,
            intervals_5m,
            timeline_start=timeline_start,
            current_price=general_price_forecast_full[0].price if general_price_forecast_full else general_price,
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

        # Set the import price to be at least 10c higher than the export price to reflect reality
        for i, import_price in enumerate(general_extrapolated_forecast):
            export_price = feed_in_extrapolated_forecast[i] if i < len(feed_in_extrapolated_forecast) else feed_in_price
            if(import_price < export_price):
                general_extrapolated_forecast[i] = export_price + 10

        self.data = price_data(
            demand_tarrif_price=self.demand_tarrif_price,
            general_price=round(general_price),
            feedIn_price=round(feed_in_price),
            prices_estimated=False,
            general_max_forecast_price=round(general_max_price),
            feedIn_max_forecast_price=round(feed_in_max_price),
            general_extrapolated_forecast=general_extrapolated_forecast,
            feedIn_extrapolated_forecast=feed_in_extrapolated_forecast,
            demand_window_extrapolated_forecast=demand_window_extrapolated_forecast,
        )
        return self.data