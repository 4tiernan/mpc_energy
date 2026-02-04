from homeassistant.helpers.update_coordinator import DataUpdateCoordinatorEntity
from homeassistant.helpers.entity import EntityCategory
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EffectivePriceSensor(coordinator)])


class EffectivePriceSensor(DataUpdateCoordinatorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Effective Price"
        self._attr_unique_id = "mpc_energy_effective_price"
        self._attr_unit_of_measurement = "$/kWh" 
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self.coordinator.data["effective_price"]
