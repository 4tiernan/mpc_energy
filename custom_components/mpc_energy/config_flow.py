import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from .const import DOMAIN

class MPCEnergyFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for MPC Energy."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(
                title="MPC Energy",
                data=user_input,
            )

        schema = vol.Schema(
            {
                vol.Required("battery_entity"): selector.EntitySelector(),
                vol.Required("price_entity"): selector.EntitySelector(),
                vol.Optional("solar_entity"): selector.EntitySelector(),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
        )
