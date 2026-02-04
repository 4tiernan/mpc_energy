from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

# Setup the entity in HA
async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id] # Retrieve coordinator instance defined in __init__.py
    async_add_entities([EffectivePriceSensor(coordinator)]) # Creates the entity in HA


class EffectivePriceSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Effective Price"
        self._attr_unique_id = "mpc_energy_effective_price"
        self._attr_unit_of_measurement = "$/kWh"
        self._attr_state_class = "measurement"  # key to history graph
        #self._attr_device_class = "power"

    @property
    def native_value(self): # Method to return the state to HA when it needs it
        if self.coordinator.data is None:
            return None
        return self.coordinator.data["effective_price"] # Pull the state directly from the coordinator
