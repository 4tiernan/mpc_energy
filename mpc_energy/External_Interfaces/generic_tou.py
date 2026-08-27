from datetime import datetime, timedelta
import json
import math
from External_Interfaces.amber_api import PriceForecast, price_data
from mpc_logger import logger


class GenericTOUInterface:
    """
    Simple time-of-use price provider defined by daily windows (repeats each day).
    Expects JSON strings for import/export windows saved by the UI as lists of
    {"start":"HH:MM","end":"HH:MM","price":cents}
    """

    def __init__(self, ha, import_windows_json: str, export_windows_json: str, demand_tarrif_price=None, demand_tarrif_window_start=None, demand_tarrif_window_end=None):
        self.ha = ha # For Timezone awareness
        self.demand_tarrif_price = None
        self.demand_tarrif_window_start = None
        self.demand_tarrif_window_end = None
        self.demand_tarrif = False
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
        if demand_tarrif_price is not None and demand_tarrif_price != "":
            try:
                self.demand_tarrif_price = float(demand_tarrif_price)
                self.demand_tarrif_window_start = demand_tarrif_window_start
                self.demand_tarrif_window_end = demand_tarrif_window_end
                self.demand_tarrif = True
                logger.info(f"Generic TOU demand tarrif enabled at ${self.demand_tarrif_price}/kW from {self.demand_tarrif_window_start} to {self.demand_tarrif_window_end}.")
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
                if s <= t <= e:
                    return p
            elif s > e:
                # overnight window (e.g. 22:00 - 06:00)
                if t >= s or t <= e:
                    return p
            else:
                return p

        return 0.0

    def _build_5min_forecast(self, windows, required_5min_periods: int, timeline_start: datetime):
        intervals = []
        for i in range(required_5min_periods):
            start = timeline_start + timedelta(minutes=i * 5)
            end = start + timedelta(minutes=5)
            price = self._price_for_min(windows, start)
            intervals.append(PriceForecast(price=price, start_time=start, end_time=end, demand_window=False))
        return intervals

    def _build_demand_window_5min(self, intervals_5m, timeline_start):
        if not self.demand_tarrif or not self.demand_tarrif_window_start or not self.demand_tarrif_window_end:
            return [False] * intervals_5m

        try:
            sh, sm = [int(x) for x in str(self.demand_tarrif_window_start).split(":")[:2]]
            eh, em = [int(x) for x in str(self.demand_tarrif_window_end).split(":")[:2]]
        except Exception:
            logger.warning("Invalid generic demand window format; disabling demand window forecast.")
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
                in_window = (m >= start_min) or (m < end_min)
            else:
                in_window = True

            out.append(in_window)

        return out

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

        timeline_start = sim_start if sim_start is not None else now
        timeline_start = timeline_start.replace(second=0, microsecond=0)

        general_price_forecast_full = self._build_5min_forecast(
            self.import_windows, intervals_5m, timeline_start
        )
        feed_in_price_forecast_full = self._build_5min_forecast(
            self.export_windows, intervals_5m, timeline_start
        )

        general_extrapolated_forecast = [round(pf.price) for pf in general_price_forecast_full]
        feed_in_extrapolated_forecast = [round(pf.price) for pf in feed_in_price_forecast_full]

        general_max_price = max((pf.price for pf in general_price_forecast_full), default=0)
        feed_in_max_price = max((pf.price for pf in feed_in_price_forecast_full), default=0)

        # current prices (cents)
        current_general = self._price_for_min(self.import_windows, now)
        current_feed_in = self._price_for_min(self.export_windows, now)

        demand_window_extrapolated_forecast = self._build_demand_window_5min(
            intervals_5m=intervals_5m,
            timeline_start=timeline_start,
        )

        self.data = price_data(
            demand_tarrif_price=self.demand_tarrif_price if self.demand_tarrif else None,
            general_price=round(current_general),
            feedIn_price=round(current_feed_in),
            prices_estimated=False,  # Generic TOU prices are fixed, not estimated
            general_max_forecast_price=round(general_max_price),
            feedIn_max_forecast_price=round(feed_in_max_price),
            general_extrapolated_forecast=general_extrapolated_forecast,
            feedIn_extrapolated_forecast=feed_in_extrapolated_forecast,
            demand_window_extrapolated_forecast=demand_window_extrapolated_forecast,
        )

        return self.data
