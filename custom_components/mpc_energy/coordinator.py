import logging
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from datetime import timedelta
from .const import DEFAULT_NAME

_LOGGER = logging.getLogger(__name__)


class MPCCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(
            hass,
            _LOGGER,
            name=DEFAULT_NAME,
            update_interval=timedelta(minutes=1),
        )
        self.hass = hass
        self.entry = entry

    async def _async_update_data(self):
        battery_power_entity = self.entry.data["battery_power"]

        state = self.hass.states.get(battery_power_entity)
        if state is None or state.state in ("unknown", "unavailable"):
            return None

        battery_power = float(state.state)

        # For now: effective price == battery power
        effective_price = battery_power

        return {
            "effective_price": effective_price,
            "battery_power": battery_power,
        }