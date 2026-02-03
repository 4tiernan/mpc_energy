from homeassistant.helpers.entity import Entity
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([EffectivePriceSensor()])

class EffectivePriceSensor(Entity):
    def __init__(self):
        self._state = None

    @property
    def name(self):
        return "Effective Price"

    @property
    def unique_id(self):
        return "mpc_energy_effective_price"

    @property
    def state(self):
        return self._state

    async def async_update(self):
        # Example: set your MPC value
        self._state = 31
