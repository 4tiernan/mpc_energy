import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

@config_entries.HANDLERS.register(DOMAIN)
class MPCEnergyFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for MPC Energy."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if user_input is not None:
            return self.async_create_entry(title="MPC Energy", data=user_input)

        schema = vol.Schema({
            vol.Required("battery_entity"): cv.entity_id,
            vol.Required("price_entity"): cv.entity_id,
            vol.Optional("solar_entity"): cv.entity_id,
        })
        return self.async_show_form(step_id="user", data_schema=schema)
