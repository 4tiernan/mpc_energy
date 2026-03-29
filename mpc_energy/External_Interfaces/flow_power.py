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
        self.general_price_entity_id = import_price_entity_id
        self.feed_in_price_entity_id = export_price_entity_id
        self.price_forecast_entity_id = price_forecast_entity_id

        logger.error("Demand pricing not yet supported in Flow Power mode.")
        self.demand_tarrif = False
        self.demand_tarrif_price = None

        if self.general_price_entity_id == "" or self.feed_in_price_entity_id == "" or self.price_forecast_entity_id == "":
            raise ValueError(
                "Flow Power mode selected but one or more Flow Power entity IDs are blank. "
                "Please set all required Flow Power entity IDs."
            ) from None

    def _get_numeric_state(self, entity_id):
        state_payload = self.ha.get_state(entity_id)
        state = state_payload.get("state")
        logger.info(f"Retrieved state_payload for entity '{entity_id}': {state_payload}")
        try:
            return float(state)
        except Exception as e:
            raise ValueError(
                f"Unable to convert state '{state}' for entity '{entity_id}' to float. "
                "Please check the entity returns a numeric c/kWh value."
            ) from e

    def _build_flat_forecast(self, price, periods, period_minutes=30):
        now = datetime.now(self.ha.local_tz).replace(second=0, microsecond=0)
        intervals = []
        for i in range(periods):
            start = now + timedelta(minutes=i * period_minutes)
            end = start + timedelta(minutes=period_minutes)
            intervals.append(
                PriceForecast(price=price, start_time=start, end_time=end, demand_window=False)
            )
        return intervals

    def get_data(self, partial_update=False, forecast_hrs=None, sim_start=None, sim_end=None):
        general_price = self._get_numeric_state(self.import_price_entity_id)
        feed_in_price = self._get_numeric_state(self.export_price_entity_id)
        self.price_forecast_entity_id = self._get_numeric_state(self.price_forecast_entity_id)

        if feed_in_price < -1000:
            logger.warning(
                "Flow feed-in price appears unexpectedly low. "
                "Confirm the entity units are in c/kWh."
            )

        general_price_forecast = self._build_flat_forecast(general_price, periods=24, period_minutes=30)
        feed_in_price_forecast = self._build_flat_forecast(feed_in_price, periods=24, period_minutes=30)

        sorted_general_forecast = sorted(general_price_forecast, key=lambda x: x.price, reverse=True)
        sorted_feed_in_forecast = sorted(feed_in_price_forecast, key=lambda x: x.price, reverse=True)

        if forecast_hrs is None:
            forecast_hrs = 24

        if sim_start is not None and sim_end is not None and sim_end > sim_start:
            forecast_minutes = (sim_end - sim_start).total_seconds() / 60.0
            intervals_5m = max(int(math.ceil(forecast_minutes / 5.0)), 1)
        else:
            intervals_5m = max(int(math.ceil(forecast_hrs * 12)), 1)

        general_extrapolated_forecast = [round(general_price)] * intervals_5m
        feed_in_extrapolated_forecast = [round(feed_in_price)] * intervals_5m
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
