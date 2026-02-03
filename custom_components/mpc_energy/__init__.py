from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import (
    DOMAIN,
    DEFAULT_NAME
)

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up MPC Energy from YAML (not used)."""
    return True

async def async_setup_entry(hass, entry):
    # Forward setup to the sensor platform
    hass.async_create_task(
        hass.config_entries.async_forward_entry_setup(entry, "sensor")
    )
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return True



##### LOGGGING !!!!!!!

