# Module to retreive the config values from the app configuration page, App must be reloaded for changes to take effect
import json
import os
from mpc_logger import logger
import migration

CONFIG_PATH = "/data/mpc_config.json"
OPTIONS_PATH = "/data/options.json"
PLANT_CONFIG_PATH = "/data/plant_config.json"
RESTART_SIGNAL_PATH = "/data/restart_signal"

def trigger_restart():
    """Writes a restart signal file to be picked up by the main process."""
    with open(RESTART_SIGNAL_PATH, "w") as f:
        f.write("restart")

def load_config():
    """Merges HA options with local dashboard configuration."""
    config = {}
    if os.path.exists(OPTIONS_PATH):
        try:
            with open(OPTIONS_PATH) as f:
                config.update(json.load(f))
        except Exception as e:
            logger.error(f"Failed to load HA options: {e}")
    
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                config.update(json.load(f))
        except Exception as e:
            logger.error(f"Failed to load local config: {e}")

    if os.path.exists(PLANT_CONFIG_PATH):
        try:
            with open(PLANT_CONFIG_PATH) as f:
                config.update(json.load(f))
        except Exception as e:
            logger.error(f"Failed to load plant config: {e}")

    return config

# Run migration before loading to ensure local files are up to date with HA options
migration.migrate_config()

options = load_config()

def save_local_config(new_config):
    """Saves web-UI managed configuration to local storage."""
    current_config = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            current_config = json.load(f)
    
    current_config.update(new_config)
    with open(CONFIG_PATH, "w") as f:
        json.dump(current_config, f, indent=4)

def get_next_setup_step():
    """Returns the streamlit page path for the first missing configuration step."""
    from plants.plant_manager import load_plant_config
    
    config = load_config()
    plant_config = load_plant_config()

    if not config.get("accepted_risks") or not config.get("ha_mqtt_user"):
        return "pages/01_General_Configuration.py"
    if not plant_config.get("plant_brand"):
        return "pages/plant_config_page.py"
    if not config.get("energy_retailer"):
        return "pages/02_Retailer_Configuration.py"
    if not config.get("solcast_forecast_today_entity_id"):
        return "pages/03_Solar_Forecast_Configuration.py"
    return None

def get_entity_id(key, default=None):
    value = options.get(key, default)
    if (value == None or value == "") and default is None:
        logger.debug(f"Configuration key '{key}' is missing or empty. Please set it in the app configuration page.")
    return value

accepted_risks = get_entity_id("accepted_risks")

MQTT_USER = get_entity_id("ha_mqtt_user")
MQTT_PASS = get_entity_id("ha_mqtt_pass")

# Retailer Configuration (Moved to Web UI)
energy_retailer = get_entity_id("energy_retailer")
demand_price = get_entity_id("demand_price")
demand_window_start = get_entity_id("demand_window_start")
demand_window_end = get_entity_id("demand_window_end")
amber_api_key = get_entity_id("amber_api_key")
amber_site_id = get_entity_id("amber_site_id")
flow_import_price_entity_id = get_entity_id("flow_import_price_entity_id")
flow_export_price_entity_id = get_entity_id("flow_export_price_entity_id")
flow_price_forecast_entity_id = get_entity_id("flow_price_forecast_entity_id")

# Solar Forecast Configuration (Moved to Web UI)
solcast_forecast_today_entity_id = get_entity_id("solcast_forecast_today_entity_id")
solcast_forecast_tomorrow_entity_id = get_entity_id("solcast_forecast_tomorrow_entity_id")
solcast_forecast_day_3_entity_id = get_entity_id("solcast_forecast_day_3_entity_id")
solcast_forecast_day_4_entity_id = get_entity_id("solcast_forecast_day_4_entity_id")
solcast_solar_kwh_remaining_today_entity_id = get_entity_id("solcast_solar_kwh_remaining_today_entity_id")
solcast_solar_power_this_hour_entity_id = get_entity_id("solcast_solar_power_this_hour_entity_id")

# Plant Configuration (Moved to Web UI)
battery_discharge_cost = get_entity_id("battery_discharge_cost")
estimated_daily_load_energy_consumption = get_entity_id("estimated_daily_load_energy_consumption")

# Core settings remaining in config.yaml
spike_price_warning_level = get_entity_id("spike_price_warning_level", default=25)
notification_target = get_entity_id("notification_target", default="")
notification_target_option = get_entity_id("notification_target_option", default="both")
log_level = get_entity_id("log_level", default="info")
