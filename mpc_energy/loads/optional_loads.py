import json
import os
from typing import Any
import cvxpy as cp
import numpy as np
from mpc_logger import logger
from ha_api import HomeAssistantAPI

DEFAULT_PATH = "/data/optional_loads.json"
LOAD_CLASSES = {}


def _storage_path() -> str:
    configured_path = os.environ.get("MPC_OPTIONAL_LOADS_PATH", DEFAULT_PATH)
    storage_dir = os.path.dirname(configured_path)
    if storage_dir and os.path.isdir(storage_dir):
        return configured_path

    # Fallback for local/dev runs where /data is not mounted.
    return os.path.join(os.path.dirname(__file__), "optional_loads.json")

def create_load_instance(item: dict[str, Any]) -> "OptionalLoad | None":
    """Factory function to create a specific load instance based on load_type."""
    l_type = str(item.get("load_type", "ev")).strip().lower()
    if l_type == "hot_water":
        from loads.HW_load import HWLoad
        return HWLoad.from_dict(item)
    elif l_type == "ev":    
        from loads.EV_load import EVLoad
        return EVLoad.from_dict(item)
    else:
        logger.warning(f"Unknown load_type '{l_type}' in item: {item}. Skipping.")
        return None

def load_optional_load_instances(ha: HomeAssistantAPI, local_tz, ha_mqtt):
    """Factory function to load and initialize instances ready for use."""
    raw_configs = load_optional_loads()
    instances = []
    for cfg in raw_configs:
        instance = create_load_instance(cfg)
        if instance:
            instance.ha = ha
            instance.local_tz = local_tz
            instance.ha_mqtt = ha_mqtt
            instances.append(instance)

    if instances:
        logger.info(f"{len(instances)} Optional Loads Configured.")
    else:
        logger.info("No optional loads configured.")

    return instances

def get_mpc_loads(ha, local_tz, ha_mqtt):
    """Alias for main.py compatibility and clean MPC init."""
    return load_optional_load_instances(ha, local_tz, ha_mqtt)

class OptionalLoad:
    def __init__(
        self,
        name: str,
        load_type: str,
        reward_cents_per_kwh: float
    ):
        # Configuration parameters
        self.name = name
        self.load_type = load_type
        self.reward_cents_per_kwh = reward_cents_per_kwh
        
        # MPC References
        self.ha: HomeAssistantAPI = None
        self.ha_mqtt = None
        self.local_tz = None

    @classmethod
    def from_dict(cls, item: dict[str, Any]) -> Any:
        """Base from_dict. Subclasses should implement their own that calls this for base fields."""
        raise NotImplementedError("Subclasses must implement from_dict method")

    def to_dict(self) -> dict[str, Any]:
        """Base to_dict. If called on OptionalLoad, returns base fields. Subclasses should extend this."""
        raise NotImplementedError("Subclasses must implement to_dict method")

    # --- MPC Interface Stubs ---
    def get_historical_power(self, start, end, bin_period):
        """Retrieve and bin historical power usage for this device."""
        raise NotImplementedError("Must implement get_historical_power in subclass")

    def build_cvxpy(self, n, dt, mpc_soc, mpc_soc_min_param):
        """Define CVXPY variables, constraints and rewards."""
        raise NotImplementedError("Must implement build_cvxpy in subclass")

    def update_mpc_values(self, n, dt, time_index, load_5min):
        """Update CVXPY parameters based on latest forecasts/state."""
        raise NotImplementedError("Must implement update_mpc_values in subclass")

    def get_results(self, dt):
        """Extract results from the solver."""
        raise NotImplementedError("Must implement get_results in subclass")


def load_optional_loads() -> list[dict[str, Any]]:
    path = _storage_path()
    if not os.path.exists(path):
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(data, list):
        return []

    return data


def save_optional_loads(load_configs: list[dict[str, Any]]) -> None:
    cleaned: list[dict[str, Any]] = []
    for item in load_configs:
        if not isinstance(item, dict):
            continue

        if not item.get("name"):
            continue

        load = create_load_instance(item)
        if load is None:
            continue

        cleaned.append(load.to_dict())

    path = _storage_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, indent=2)