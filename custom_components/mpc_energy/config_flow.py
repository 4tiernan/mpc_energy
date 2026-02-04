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

        vol.Required("EMS Controlled By Home Assistant Switch (switch)"): selector.EntitySelector(),
        vol.Required("EMS Control Mode (dropdown)"): selector.EntitySelector(),
        vol.Required("Discharge Limiter (number input)"): selector.EntitySelector(),
        vol.Required("Charge Limiter (number input)"): selector.EntitySelector(),
        vol.Required("PV Limiter (number input)"): selector.EntitySelector(),
        vol.Required("Export Limiter (number input)"): selector.EntitySelector(),
        vol.Required("Import Limiter (number input)"): selector.EntitySelector(),


        vol.Required("Battery Rated Capacity (kWh)"): selector.EntitySelector(),
        vol.Optional("Backup Buffer SOC (%)"): selector.EntitySelector(),
        vol.Required("Charge Cut-Off SOC (%)"): selector.EntitySelector(),
        vol.Required("Battery Charge Power Limit (kW)"): selector.EntitySelector(),
        vol.Required("Battery Discharge Power Limit (kW)"): selector.EntitySelector(),
        vol.Required("Battery SOC (%)"): selector.EntitySelector(),

        vol.Required("Solar MPPT DC Power Limit (kW)"): selector.EntitySelector(),
        vol.Required("Inverter AC Power Limit (kW)"): selector.EntitySelector(),
        vol.Required("Grid Import Power Limit (kW)"): selector.EntitySelector(),
        vol.Required("Grid Export Power Limit (kW)"): selector.EntitySelector(),

        vol.Required("Load Power (kW)"): selector.EntitySelector(),
        vol.Required("Solar Power (kW)"): selector.EntitySelector(),
        vol.Required("Battery Power (kW)(+dis, -chg)"): selector.EntitySelector(),
        vol.Required("Inverter Power (kW)(+generating, -consuming)"): selector.EntitySelector(),
        vol.Required("Grid Power (kW)(-export, +import)"): selector.EntitySelector(),
        

        vol.Required("Solcast Solar Forecast Today (kWh)"): selector.EntitySelector(),


        #vol.Required("price_entity"): selector.EntitySelector(),
        #vol.Optional("solar_entity"): selector.EntitySelector(),
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