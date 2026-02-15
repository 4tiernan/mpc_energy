import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from .const import DOMAIN, PlantEntityReferences


def create_schema(entry=None):
    get_default = lambda key, fallback=None: entry.data.get(key, fallback) if entry else fallback

    schema = vol.Schema( # Define all inputs to the integration.
        {
            
            vol.Required(PlantEntityReferences.BATTERY_DISCHARGE_COST, default=get_default(PlantEntityReferences.BATTERY_DISCHARGE_COST, 0)): selector.NumberSelector(selector.NumberSelectorConfig(
                    min=0,
                    max=1,
                    step=0.001,
                    unit_of_measurement="$/kWh",
                    mode=selector.NumberSelectorMode.BOX,
            )),

            # Amber API Key Input
            vol.Required(PlantEntityReferences.AMBER_API_KEY, default=get_default(PlantEntityReferences.AMBER_API_KEY, "psk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"),): selector.TextSelector(selector.TextSelectorConfig(multiline=False)),

            # Amber API Site ID Input
            vol.Required(PlantEntityReferences.AMBER_API_SITE_ID, default=get_default(PlantEntityReferences.AMBER_API_SITE_ID, "xxxxxxxxxxxxxxxxxxxxxxxxxx"),): selector.TextSelector(selector.TextSelectorConfig(multiline=False)),

            vol.Required(PlantEntityReferences.HA_EMS_CONTROL_SWITCH): selector.EntitySelector(),
            vol.Required(PlantEntityReferences.EMS_CONTROL_MODE): selector.EntitySelector(),
            vol.Required(PlantEntityReferences.DISCHARGE_LIMITER): selector.EntitySelector(),
            vol.Required(PlantEntityReferences.CHARGE_LIMITER): selector.EntitySelector(),
            vol.Required(PlantEntityReferences.PV_LIMTER): selector.EntitySelector(),
            vol.Required(PlantEntityReferences.EXPORT_LIMITER): selector.EntitySelector(),
            vol.Required(PlantEntityReferences.IMPORT_LIMTER): selector.EntitySelector(),


            vol.Required(PlantEntityReferences.BATTERY_RATED_CAPACITY): selector.EntitySelector(),
            vol.Optional(PlantEntityReferences.BACKUP_SOC): selector.EntitySelector(),
            vol.Required(PlantEntityReferences.CHARGE_CUTOFF_SOC): selector.EntitySelector(),
            
            vol.Required(PlantEntityReferences.BATTERY_SOC): selector.EntitySelector(),

            vol.Required(PlantEntityReferences.CHARGE_LIMIT): selector.EntitySelector(),
            vol.Required(PlantEntityReferences.DISCHARGE_LIMIT): selector.EntitySelector(),
            vol.Required(PlantEntityReferences.PV_LIMIT): selector.EntitySelector(),
            vol.Required(PlantEntityReferences.INVERTER_LIMIT): selector.EntitySelector(),
            vol.Required(PlantEntityReferences.IMPORT_LIMIT): selector.EntitySelector(),
            vol.Required(PlantEntityReferences.EXPORT_LIMIT): selector.EntitySelector(),

            vol.Required(PlantEntityReferences.LOAD_POWER): selector.EntitySelector(),
            vol.Required(PlantEntityReferences.SOLAR_POWER): selector.EntitySelector(),
            vol.Required(PlantEntityReferences.BATTERY_POWER, default=get_default(PlantEntityReferences.BATTERY_POWER)): selector.EntitySelector(),
            vol.Required(PlantEntityReferences.INVERTER_POWER): selector.EntitySelector(),
            vol.Required(PlantEntityReferences.GRID_POWER): selector.EntitySelector(),
            

            vol.Required(PlantEntityReferences.SOLCAST_FORECAST): selector.EntitySelector(),


            #vol.Required("price_entity"): selector.EntitySelector(),
            #vol.Optional("solar_entity"): selector.EntitySelector(),
        }
    )
    return schema


class MPCEnergyFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for MPC Energy."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(
                title="MPC Energy",
                data=user_input,
            )
        
        schema = create_schema()

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
        )
        
    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()  # get the existing config entry

        if user_input is not None:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(),
                data_updates=user_input,
            )
        
        schema = create_schema(entry)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
        )