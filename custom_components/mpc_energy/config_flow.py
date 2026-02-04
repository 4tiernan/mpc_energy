import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from .const import DOMAIN, PlantEntites



schema = vol.Schema( # Define all inputs to the integration.
    {
        vol.Required(PlantEntites.BATTERY_DISCHARGE_COST): selector.NumberSelector(selector.NumberSelectorConfig(
                min=0,
                max=1,
                step=0.001,
                unit_of_measurement="$/kWh",
                mode=selector.NumberSelectorMode.BOX,
            )),

        vol.Required(PlantEntites.HA_EMS_CONTROL_SWITCH): selector.EntitySelector(),
        vol.Required(PlantEntites.EMS_CONTROL_MODE): selector.EntitySelector(),
        vol.Required(PlantEntites.DISCHARGE_LIMITER): selector.EntitySelector(),
        vol.Required(PlantEntites.CHARGE_LIMITER): selector.EntitySelector(),
        vol.Required(PlantEntites.PV_LIMTER): selector.EntitySelector(),
        vol.Required(PlantEntites.EXPORT_LIMITER): selector.EntitySelector(),
        vol.Required(PlantEntites.IMPORT_LIMTER): selector.EntitySelector(),


        vol.Required(PlantEntites.BATTERY_RATED_CAPACITY): selector.EntitySelector(),
        vol.Optional(PlantEntites.BACKUP_SOC): selector.EntitySelector(),
        vol.Required(PlantEntites.CHARGE_CUTOFF_SOC): selector.EntitySelector(),
        
        vol.Required(PlantEntites.BATTERY_SOC): selector.EntitySelector(),

        vol.Required(PlantEntites.CHARGE_LIMIT): selector.EntitySelector(),
        vol.Required(PlantEntites.DISCHARGE_LIMIT): selector.EntitySelector(),
        vol.Required(PlantEntites.PV_LIMIT): selector.EntitySelector(),
        vol.Required(PlantEntites.INVERTER_LIMIT): selector.EntitySelector(),
        vol.Required(PlantEntites.IMPORT_LIMIT): selector.EntitySelector(),
        vol.Required(PlantEntites.EXPORT_LIMIT): selector.EntitySelector(),

        vol.Required(PlantEntites.LOAD_POWER): selector.EntitySelector(),
        vol.Required(PlantEntites.SOLAR_POWER): selector.EntitySelector(),
        vol.Required(PlantEntites.BATTERY_POWER): selector.EntitySelector(),
        vol.Required(PlantEntites.INVERTER_POWER): selector.EntitySelector(),
        vol.Required(PlantEntites.GRID_POWER): selector.EntitySelector(),
        

        vol.Required(PlantEntites.SOLCAST_FORECAST): selector.EntitySelector(),


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