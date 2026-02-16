# Module to retreive the config values from the app configuration page, App must be reloaded for changes to take effect
import json

with open("/data/options.json") as f:
    options = json.load(f)

def get_val(key, default=None):
    value = options.get(key, default)
    if(value == None or value == ""):
        raise Exception(f"Failed to get {key} from user configuration")

log_level = get_val("log_level")
ha_api_key = get_val("ha_api_key")
ha_mqtt_user = get_val("ha_mqtt_user")
ha_mqtt_pass = get_val("ha_mqtt_pass")


amber_api_key = get_val("amber_api_key")
amber_site_id = get_val("amber_site_id")
battery_discharge_cost = get_val("battery_discharge_cost")

ha_ems_control_switch_entity_id = get_val("ha_ems_control_switch_entity_id")
ems_control_mode_entity_id = get_val("ems_control_mode_entity_id")
battery_discharge_limiter_entity_id = get_val("battery_discharge_limiter_entity_id")
battery_charge_limiter_entity_id = get_val("battery_charge_limiter_entity_id")
pv_limiter_entity_id = get_val("pv_limiter_entity_id")
export_limiter_entity_id = get_val("export_limiter_entity_id")
import_limiter_entity_id = get_val("import_limiter_entity_id")

battery_rated_capacity_entity_id = get_val("battery_rated_capacity_entity_id")
backup_soc_entity_id = get_val("backup_soc_entity_id")
charge_cutoff_soc_entity_id = get_val("charge_cutoff_soc_entity_id")

battery_max_charge_power_limit_entity_id = get_val("battery_max_charge_power_limit_entity_id")
battery_max_discharge_power_limit_entity_id = get_val("battery_max_discharge_power_limit_entity_id")
pv_max_power_limit_entity_id = get_val("pv_max_power_limit_entity_id")
import_max_power_limit_entity_id = get_val("import_max_power_limit_entity_id")
export_max_power_limit_entity_id = get_val("export_max_power_limit_entity_id")

load_power_entity_id = get_val("load_power_entity_id")
solar_power_entity_id = get_val("solar_power_entity_id")
battery_power_entity_id = get_val("battery_power_entity_id")
inverter_power_entity_id = get_val("inverter_power_entity_id")
grid_power_entity_id = get_val("grid_power_entity_id")

solcast_forecast_entity_id = get_val("solcast_forecast_entity_id")
