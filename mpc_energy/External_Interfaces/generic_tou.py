from datetime import datetime, timedelta
import json
import math
from External_Interfaces.amber_api import PriceForecast, amber_data
from mpc_logger import logger


class GenericTOUInterface:
    """
    Simple time-of-use price provider defined by daily windows (repeats each day).
    Expects JSON strings for import/export windows saved by the UI as lists of
    {"start":"HH:MM","end":"HH:MM","price":cents}
    """

    def __init__(self, ha, import_windows_json: str, export_windows_json: str, demand_tarrif_price=None, demand_tarrif_window_start=None, demand_tarrif_window_end=None):
        self.ha = ha # For Timezone awareness
        try:
            self.import_windows = json.loads(import_windows_json) if import_windows_json else []
        except Exception:
            logger.error("Failed to parse generic_import_windows JSON, defaulting to empty list")
            self.import_windows = []
        try:
            self.export_windows = json.loads(export_windows_json) if export_windows_json else []
        except Exception:
            logger.error("Failed to parse generic_export_windows JSON, defaulting to empty list")
            self.export_windows = []

        # Demand tariff handling (optional)
        self.demand_tarrif_price = None
        self.demand_tarrif = False
        if demand_tarrif_price is not None and demand_tarrif_price != "":
            try:
                self.demand_tarrif_price = float(demand_tarrif_price)
                self.demand_tarrif = True
            except Exception:
                logger.warning("Invalid demand tariff price for Generic TOU; disabling demand tariff.")    

    def _price_for_min(self, windows, dt: datetime):
        # windows: list of dicts {start,end,price}
        # Use datetime/time comparisons so we can support overnight windows
        t = dt.time()
        for w in windows:
            try:
                s_str = w.get("start", "00:00")
                e_str = w.get("end", "23:59")
                s = datetime.strptime(s_str, "%H:%M").time()
                e = datetime.strptime(e_str, "%H:%M").time()
                p = float(w.get("price", 0.0))
            except Exception:
                continue

            if s < e:
                if s <= t < e:
                    return p
            elif s > e:
                # overnight window (e.g. 22:00 - 06:00)
                if t >= s or t < e:
                    return p
            else:
                return p

        return 0.0

    def _build_30min_forecast(self, required_30min_periods: int, timeline_start: datetime):
        # Align timeline_start down to 30-minute boundary
        horizon_start = timeline_start.replace(minute=(timeline_start.minute // 30) * 30, second=0, microsecond=0)
        intervals = []
        for i in range(required_30min_periods):
            start = horizon_start + timedelta(minutes=i * 30)
            import_price = self._price_for_min(self.import_windows, start)
            export_price = self._price_for_min(self.export_windows, start)
            end = start + timedelta(minutes=30)
            intervals.append(PriceForecast(price=import_price, start_time=start, end_time=end, demand_window=False))
        return intervals

    def _forecast_to_5min(self, forecast_30min, intervals_5m, timeline_start, current_price):
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
        # Determine time horizon
        now = datetime.now(self.ha.local_tz)
        if forecast_hrs is None:
            forecast_hrs = 24

        if sim_start is not None and sim_end is not None and sim_end > sim_start:
            forecast_minutes = (sim_end - sim_start).total_seconds() / 60.0
            intervals_5m = max(int(math.ceil(forecast_minutes / 5.0)), 1)
        else:
            intervals_5m = max(int(math.ceil(forecast_hrs * 12)), 1)

        required_30min_periods = max(int(math.ceil(intervals_5m / 6.0)), 1)

        timeline_start = sim_start if sim_start is not None else now
        timeline_start = timeline_start.replace(second=0, microsecond=0)

        general_price_forecast_full = self._build_30min_forecast(required_30min_periods, timeline_start)
        feed_in_price_forecast_full = []
        # Build separate feed-in forecast with export prices
        for pf in general_price_forecast_full:
            export_price = self._price_for_min(self.export_windows, pf.start_time)
            feed_in_price_forecast_full.append(PriceForecast(price=export_price, start_time=pf.start_time, end_time=pf.end_time, demand_window=False))

        general_extrapolated_forecast = self._forecast_to_5min(
            general_price_forecast_full,
            intervals_5m,
            timeline_start=timeline_start,
            current_price=general_price_forecast_full[0].price if general_price_forecast_full else 0,
        )

        feed_in_extrapolated_forecast = self._forecast_to_5min(
            feed_in_price_forecast_full,
            intervals_5m,
            timeline_start=timeline_start,
            current_price=feed_in_price_forecast_full[0].price if feed_in_price_forecast_full else 0,
        )

        sorted_general_forecast = sorted(general_price_forecast_full, key=lambda x: x.price, reverse=True)
        sorted_feed_in_forecast = sorted(feed_in_price_forecast_full, key=lambda x: x.price, reverse=True)

        # current prices (cents)
        current_general = self._price_for_min(self.import_windows, now)
        current_feed_in = self._price_for_min(self.export_windows, now)

        self.data = amber_data(
            demand_tarrif_price=self.demand_tarrif_price if self.demand_tarrif else None,
            general_price=round(current_general),
            feedIn_price=round(current_feed_in),
            prices_estimated=True,
            general_max_forecast_price=round(sorted_general_forecast[0].price) if sorted_general_forecast else 0,
            feedIn_max_forecast_price=round(sorted_feed_in_forecast[0].price) if sorted_feed_in_forecast else 0,
            general_12hr_forecast=general_price_forecast_full[:24],
            feedIn_12hr_forecast=feed_in_price_forecast_full[:24],
            general_12hr_forecast_sorted=sorted_general_forecast,
            feedIn_12hr_forecast_sorted=sorted_feed_in_forecast,
            general_extrapolated_forecast=general_extrapolated_forecast,
            feedIn_extrapolated_forecast=feed_in_extrapolated_forecast,
            demand_window_extrapolated_forecast=[False] * intervals_5m,
        )

        return self.data
