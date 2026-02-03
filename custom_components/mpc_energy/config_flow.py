import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from .const import DOMAIN

schema = vol.Schema( # Define all inputs to the integration.
    {
        vol.Required("Battery Discharge Cost ($/kWh)"): selector.NumberSelector(selector.NumberSelectorConfig(
                min=0,
                max=1,
                step=0.001,
                unit_of_measurement="$/kWh",
                mode=selector.NumberSelectorMode.BOX,
            )),

        vol.Required("Battery Rated Capacity"): selector.EntitySelector(),
        vol.Optional("Backup Buffer SOC"): selector.EntitySelector(),
        vol.Required("Charge Cut-Off SOC"): selector.EntitySelector(),
        vol.Required("Battery Charge Power Limit"): selector.EntitySelector(),
        vol.Required("Battery Discharge Power Limit"): selector.EntitySelector(),
        vol.Required("Battery SOC"): selector.EntitySelector(),

        vol.Required("Solar MPPT DC Power Limit"): selector.EntitySelector(),
        vol.Required("Inverter AC Power Limit"): selector.EntitySelector(),
        vol.Required("Grid Import Power Limit"): selector.EntitySelector(),
        vol.Required("Grid Export Power Limit"): selector.EntitySelector(),


        vol.Required("price_entity"): selector.EntitySelector(),
        vol.Optional("solar_entity"): selector.EntitySelector(),
        
    }
)


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
        
    async def async_step_reconfigure(self, user_input=None):
        if user_input is not None:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(),
                data_updates=user_input,
            )
        
        

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
        )