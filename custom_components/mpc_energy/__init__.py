from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import (
    DOMAIN,
    DEFAULT_NAME
)

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up MPC Energy from YAML (not used)."""
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up MPC Energy from a config entry."""
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return True



##### LOGGGING !!!!!!!

def setup(hass, config):
    hass.states.set("mpc_energy.effective_price", "31")
    
    return True # True lets HA know the integration setup succesfully.