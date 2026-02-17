# Module to retreive the config values from the app configuration page, App must be reloaded for changes to take effect
import json

with open("/data/options.json") as f:
    options = json.load(f)

def get_entity_id(key, default=None):
    value = options.get(key, default)
    if((value == None or value == "") and default == None):
        raise Exception(f"Failed to get {key} from user configuration")
    return value

log_level = get_entity_id("log_level")
MQTT_USER = get_entity_id("ha_mqtt_user")
MQTT_PASS = get_entity_id("ha_mqtt_pass")

amber_api_key = get_entity_id("amber_api_key")
amber_site_id = get_entity_id("amber_site_id", default="")
battery_discharge_cost = get_entity_id("battery_discharge_cost")
battery_power_sign_convention = get_entity_id("battery_power_sign_convention")

battery_max_discharge_power_limit_entity_id = get_entity_id("battery_max_discharge_power_limit_entity_id")
battery_max_charge_power_limit_entity_id = get_entity_id("battery_max_charge_power_limit_entity_id")
inverter_max_power_limit_entity_id = get_entity_id("inverter_max_power_limit_entity_id")
pv_max_power_limit_entity_id = get_entity_id("pv_max_power_limit_entity_id")
import_max_power_limit_entity_id = get_entity_id("import_max_power_limit_entity_id")
export_max_power_limit_entity_id = get_entity_id("export_max_power_limit_entity_id")


solcast_forecast_today_entity_id = get_entity_id("solcast_forecast_today_entity_id")
solcast_forecast_tomorrow_entity_id = get_entity_id("solcast_forecast_tomorrow_entity_id")
solcast_solar_kwh_remaining_today_entity_id = get_entity_id("solcast_solar_kwh_remaining_today_entity_id")
solcast_solar_power_this_hour_entity_id = get_entity_id("solcast_solar_power_this_hour_entity_id")

ha_ems_control_switch_entity_id = get_entity_id("ha_ems_control_switch_entity_id")
ems_control_mode_entity_id = get_entity_id("ems_control_mode_entity_id")

load_power_entity_id = get_entity_id("load_power_entity_id")
solar_power_entity_id = get_entity_id("solar_power_entity_id")
battery_power_entity_id = get_entity_id("battery_power_entity_id")
inverter_power_entity_id = get_entity_id("inverter_power_entity_id")
grid_power_entity_id = get_entity_id("grid_power_entity_id")

battery_soc_entity_id = get_entity_id("battery_soc_entity_id")
battery_stored_energy_entity_id = get_entity_id("battery_stored_energy_entity_id")
battery_kwh_till_full_entity_id = get_entity_id("battery_kwh_till_full_entity_id")
plant_solar_kwh_today_entity_id = get_entity_id("plant_solar_kwh_today_entity_id")
plant_daily_load_kwh_entity_id = get_entity_id("plant_daily_load_kwh_entity_id")

battery_rated_capacity_entity_id = get_entity_id("battery_rated_capacity_entity_id")
backup_soc_entity_id = get_entity_id("backup_soc_entity_id")
charge_cutoff_soc_entity_id = get_entity_id("charge_cutoff_soc_entity_id")

battery_discharge_limiter_entity_id = get_entity_id("battery_discharge_limiter_entity_id")
battery_charge_limiter_entity_id = get_entity_id("battery_charge_limiter_entity_id")
pv_limiter_entity_id = get_entity_id("pv_limiter_entity_id")
export_limiter_entity_id = get_entity_id("export_limiter_entity_id")
import_limiter_entity_id = get_entity_id("import_limiter_entity_id")

