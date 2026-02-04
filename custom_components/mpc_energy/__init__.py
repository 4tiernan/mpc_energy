from .const import DOMAIN
from .coordinator import MPCCoordinator

async def async_setup_entry(hass, entry):
    coordinator = MPCCoordinator(hass, entry)

    # Initial refresh
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator # Define coordinator for integration

    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])

    return True

async def async_unload_entry(hass, entry):
    """Unload entry."""
    await hass.config_entries.async_unload_platforms(entry, ["sensor"])
    return True


