# Module to retreive the config values from the app configuration page, App must be reloaded for changes to take effect
import json

with open("/data/options.json") as f:
    options = json.load(f)

def get_entity_id(key, default=None):
    value = options.get(key, default)
    if((value == None or value == "") and default == None):
        raise Exception(f"Missing required configuration: {key}. \n Please ensure this value has been set in the app configuration page and restart the app.") from None
    return value

accepted_risks = get_entity_id("accepted_risks")

MQTT_USER = get_entity_id("ha_mqtt_user")
MQTT_PASS = get_entity_id("ha_mqtt_pass")

energy_retailer = get_entity_id("energy_retailer", default="amber")
demand_price = get_entity_id("demand_price", default="")
demand_window_start = get_entity_id("demand_window_start", default="16:00")
demand_window_end = get_entity_id("demand_window_end", default="21:00")

amber_api_key = get_entity_id("amber_api_key", default="")
amber_site_id = get_entity_id("amber_site_id", default="")

flow_import_price_entity_id = get_entity_id("flow_import_price_entity_id", default="")
flow_export_price_entity_id = get_entity_id("flow_export_price_entity_id", default="")
flow_price_forecast_entity_id = get_entity_id("flow_price_forecast_entity_id", default="")

battery_discharge_cost = get_entity_id("battery_discharge_cost")
spike_price_warning_level = get_entity_id("spike_price_warning_level", default=25)
notification_target = get_entity_id("notification_target", default="")
notification_target_option = get_entity_id("notification_target_option", default="both")
estimated_daily_load_energy_consumption = get_entity_id("estimated_daily_load_energy_consumption")

ev_plugged_in_entity_id = get_entity_id("ev_plugged_in_entity_id", default="")
ev_charging_power_entity_id = get_entity_id("ev_charging_power_entity_id", default="")
ev_soc_entity_id = get_entity_id("ev_soc_entity_id", default="")
ev_battery_capacity_kwh = get_entity_id("ev_battery_capacity_kwh", default="")
ev_max_charge_power_entity_id = get_entity_id("ev_max_charge_power_entity_id", default="")
ev_min_charge_power_kw = get_entity_id("ev_min_charge_power_kw", default="")
ev_min_soc = get_entity_id("ev_min_soc", default=20)
ev_max_soc = get_entity_id("ev_max_soc", default=80)
ev_stage1_charge_reward_cents_per_kwh = get_entity_id("ev_stage1_charge_reward_cents_per_kwh", default=20)
ev_stage2_charge_reward_cents_per_kwh = get_entity_id("ev_stage2_charge_reward_cents_per_kwh", default=5)

pv_max_power_limit_entity_id = get_entity_id("pv_max_power_limit_entity_id")
import_max_power_limit_entity_id = get_entity_id("import_max_power_limit_entity_id")
export_max_power_limit_entity_id = get_entity_id("export_max_power_limit_entity_id")
battery_max_discharge_power_limit_entity_id = get_entity_id("battery_max_discharge_power_limit_entity_id")
battery_max_charge_power_limit_entity_id = get_entity_id("battery_max_charge_power_limit_entity_id")
inverter_max_power_limit_entity_id = get_entity_id("inverter_max_power_limit_entity_id")

battery_power_sign_convention = get_entity_id("battery_power_sign_convention")

solcast_forecast_today_entity_id = get_entity_id("solcast_forecast_today_entity_id")
solcast_forecast_tomorrow_entity_id = get_entity_id("solcast_forecast_tomorrow_entity_id")
solcast_forecast_day_3_entity_id = get_entity_id("solcast_forecast_day_3_entity_id")
solcast_forecast_day_4_entity_id = get_entity_id("solcast_forecast_day_4_entity_id")
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
plant_daily_import_kwh_entity_id = get_entity_id("plant_daily_import_kwh_entity_id")
plant_daily_export_kwh_entity_id = get_entity_id("plant_daily_export_kwh_entity_id")

battery_rated_capacity_entity_id = get_entity_id("battery_rated_capacity_entity_id")
backup_soc_entity_id = get_entity_id("backup_soc_entity_id")
charge_cutoff_soc_entity_id = get_entity_id("charge_cutoff_soc_entity_id")

battery_discharge_limiter_entity_id = get_entity_id("battery_discharge_limiter_entity_id")
battery_charge_limiter_entity_id = get_entity_id("battery_charge_limiter_entity_id")
pv_limiter_entity_id = get_entity_id("pv_limiter_entity_id")
export_limiter_entity_id = get_entity_id("export_limiter_entity_id")
import_limiter_entity_id = get_entity_id("import_limiter_entity_id")

log_level = get_entity_id("log_level", default="info")

