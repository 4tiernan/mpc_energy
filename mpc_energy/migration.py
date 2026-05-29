import json
import os
from mpc_logger import logger

OPTIONS_PATH = "/data/options.json"
MPC_CONFIG_PATH = "/data/mpc_config.json"
PLANT_CONFIG_PATH = "/data/plant_config.json"
OPTIONAL_LOADS_PATH = "/data/optional_loads.json"

def migrate_config():
    """
    Temporary utility to sync legacy HA options into the new local JSON files.
    This allows the transition to the Web UI while keeping settings in config.yaml.
    """
    logger.info("Migration: Starting sync check from Home Assistant options.json...")

    if not os.path.exists(OPTIONS_PATH):
        logger.debug("Migration: No legacy options.json found at /data/options.json. Skipping.")
        return

    try:
        with open(OPTIONS_PATH) as f:
            options = json.load(f)
    except Exception as e:
        logger.error(f"Migration: Failed to load HA options: {e}")
        return

    if not options.get("ha_mqtt_user") or not options.get("ha_mqtt_pass"):
        logger.info("Migration Skipped: MQTT credentials are missing from Home Assistant options. Please ignore this if this is the first time you have installed MPC")
        return

    # Mapping legacy keys to new plant_config.json keys
    plant_mapping = {
        "battery_discharge_cost": "battery_discharge_cost",
        "estimated_daily_load_energy_consumption": "estimated_daily_load_energy_consumption",
        "pv_max_power_limit_entity_id": "pv_max_power_limit_entry",
        "import_max_power_limit_entity_id": "import_max_power_limit_entry",
        "export_max_power_limit_entity_id": "export_max_power_limit_entry",
        "battery_max_discharge_power_limit_entity_id": "battery_max_discharge_power_limit_entry",
        "battery_max_charge_power_limit_entity_id": "battery_max_charge_power_limit_entry",
        "inverter_max_power_limit_entity_id": "inverter_max_power_limit_entry",
        "load_power_entity_id": "load_power_entity_id",
        "solar_power_entity_id": "solar_power_entity_id",
        "battery_power_entity_id": "battery_power_entity_id",
        "grid_power_entity_id": "grid_power_entity_id",
        "inverter_power_entity_id": "inverter_power_entity_id",
        "battery_soc_entity_id": "battery_soc_entity_id",
        "backup_soc_entity_id": "backup_soc_entry",
        "charge_cutoff_soc_entity_id": "charge_cutoff_soc_entry",
        "battery_rated_capacity_entity_id": "battery_rated_capacity_entry",
        "battery_kwh_till_full_entity_id": "battery_kwh_till_full_entity_id",
        "battery_stored_energy_entity_id": "battery_stored_energy_entity_id",
        "plant_daily_import_kwh_entity_id": "plant_daily_import_kwh_entity_id",
        "plant_daily_export_kwh_entity_id": "plant_daily_export_kwh_entity_id",
        "ha_ems_control_switch_entity_id": "ha_ems_control_switch_entity_id",
        "ems_control_mode_entity_id": "ems_control_mode_entity_id",
        "pv_limiter_entity_id": "pv_limiter_entity_id",
        "battery_discharge_limiter_entity_id": "battery_discharge_limiter_entity_id",
        "battery_charge_limiter_entity_id": "battery_charge_limiter_entity_id",
        "export_limiter_entity_id": "export_limiter_entity_id",
        "import_limiter_entity_id": "import_limiter_entity_id",
        "battery_power_sign_convention": "battery_power_sign_convention"
    }

    # Load current local configs
    mpc_cfg = {}
    if os.path.exists(MPC_CONFIG_PATH):
        with open(MPC_CONFIG_PATH) as f: mpc_cfg = json.load(f)

    plant_cfg = {}
    if os.path.exists(PLANT_CONFIG_PATH):
        with open(PLANT_CONFIG_PATH) as f: plant_cfg = json.load(f)

    opt_loads = []
    if os.path.exists(OPTIONAL_LOADS_PATH):
        with open(OPTIONAL_LOADS_PATH) as f: opt_loads = json.load(f)

    changed_mpc = False
    changed_plant = False
    changed_opt = False

    # Default brand to Sigenergy if migrating from legacy
    if not plant_cfg.get("plant_brand"):
        logger.info("Migration: No plant brand detected in plant_config.json, defaulting to 'Sigenergy'")
        plant_cfg["plant_brand"] = "Sigenergy"
        changed_plant = True

    for k, v in options.items():
        # Only migrate non-empty values
        if v == "" or v is None:
            continue

        if k in plant_mapping:
            new_key = plant_mapping[k]
            if plant_cfg.get(new_key) != v:
                logger.info(f"Migration: Syncing plant configuration for '{new_key}' from HA option '{k}'")
                plant_cfg[new_key] = v
                changed_plant = True
        else:
            if mpc_cfg.get(k) != v:
                logger.info(f"Migration: Syncing general configuration for '{k}' from HA option")
                mpc_cfg[k] = v
                changed_mpc = True

    if changed_mpc:
        with open(MPC_CONFIG_PATH, "w") as f:
            json.dump(mpc_cfg, f, indent=4)
        logger.info("Migration: Successfully updated mpc_config.json.")

    if changed_plant:
        with open(PLANT_CONFIG_PATH, "w") as f:
            json.dump(plant_cfg, f, indent=4)
        logger.info("Migration: Successfully updated plant_config.json.")

    if changed_opt:
        with open(OPTIONAL_LOADS_PATH, "w") as f:
            json.dump(opt_loads, f, indent=4)
        logger.info("Migration: Successfully migrated legacy EV load to optional_loads.json.")

    if not (changed_mpc or changed_plant or changed_opt):
        logger.info("Migration: Local configuration files are already up-to-date with HA options.")