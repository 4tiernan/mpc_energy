from .const import DOMAIN

async def async_setup_entry(hass, entry):
    """Set up MPC Energy from a config entry."""
    # Forward to sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    return True

async def async_unload_entry(hass, entry):
    """Unload entry."""
    await hass.config_entries.async_unload_platforms(entry, ["sensor"])
    return True
