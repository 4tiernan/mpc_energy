import json
import os
from typing import Any
import cvxpy as cp
import numpy as np
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
    from loads.EV_load import EVLoad
    return EVLoad.from_dict(item)

def load_optional_load_instances(ha, plant, local_tz, ha_mqtt):
    """Factory function to load and initialize instances ready for use."""
    raw_configs = load_optional_loads()
    instances = []
    for cfg in raw_configs:
        instance = create_load_instance(cfg)
        if instance:
            instance.ha = ha
            instance.plant = plant
            instance.local_tz = local_tz
            instance.ha_mqtt = ha_mqtt
            if ha:
                instance.update_data(ha)
            instances.append(instance)
    return instances

def get_mpc_loads(ha, plant, local_tz, ha_mqtt):
    """Alias for main.py compatibility and clean MPC init."""
    return load_optional_load_instances(ha, plant, local_tz, ha_mqtt)

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

    @property
    def charge_remaining_kwh(self) -> float:
        """Returns the energy required to reach the max target in kWh."""
        target_kwh = (self.max_limit / 100.0) * self.capacity_kwh
        return max(0.0, target_kwh - self.current_charge_kwh)

    @classmethod
    def from_dict(cls, item: dict[str, Any]) -> Any:
        """
        Base from_dict. If called on OptionalLoad, acts as a factory. 
        If called on a subclass, instantiates that subclass.
        """
        if cls is OptionalLoad:
            return create_load_instance(item)

        power_entity_id = str(item.get("power_entity_id", "")).strip()
        if not power_entity_id:
            return None

        name = str(item.get("name", power_entity_id)).strip() or power_entity_id
        return cls(
            name=name,
            power_entity_id=power_entity_id,
            load_type=str(item.get("load_type", "ev")).strip(),
            plugged_in_entity_id=str(item.get("plugged_in_entity_id", "")).strip(),
            level_entity_id=str(item.get("level_entity_id", "")).strip(),
            capacity_kwh=float(item.get("capacity_kwh", 0.0) or 0.0),
            max_charge_power_entity_id=str(item.get("max_charge_power_entity_id", "")).strip(),
            min_charge_power_kw=float(item.get("min_charge_power_kw", 0.0) or 0.0),
            min_limit=float(item.get("min_limit", 0.0) or 0.0),
            max_limit=float(item.get("max_limit", 100.0) or 100.0),
            charge_reward_cents_per_kwh=float(item.get("charge_reward_cents_per_kwh", 0.0) or 0.0)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "power_entity_id": self.power_entity_id,
            "load_type": self.load_type,
            "plugged_in_entity_id": self.plugged_in_entity_id,
            "level_entity_id": self.level_entity_id,
            "capacity_kwh": self.capacity_kwh,
            "max_charge_power_entity_id": self.max_charge_power_entity_id,
            "min_charge_power_kw": self.min_charge_power_kw,
            "min_limit": self.min_limit,
            "max_limit": self.max_limit,
            "charge_reward_cents_per_kwh": self.charge_reward_cents_per_kwh
        }

    def _get_numeric(self, ha, entity_id_or_val, default: float = 0.0) -> float:
        if not entity_id_or_val:
            return default
        try:
            return float(entity_id_or_val)
        except (ValueError, TypeError):
            try:
                state_payload = ha.get_state(entity_id_or_val)
                val = state_payload.get("state")
                return float(val) if val not in (None, "unavailable", "unknown") else default
            except Exception:
                return default

    def _get_bool(self, ha, entity_id, default: bool = False) -> bool:
        if not entity_id:
            return default
        try:
            state_payload = ha.get_state(entity_id)
            state = str(state_payload.get("state", "")).strip().lower()
            true_states = {"on", "true", "home", "connected", "plugged", "plugged_in", "yes"}
            return state in true_states
        except Exception:
            return default

    # --- MPC Interface Stubs ---
    def debias_load(self, current_load, historical_data):
        """Remove current device power from load to avoid feedback loops."""
        return current_load
        
    def get_historical_power(self, start, end, bin_period):
        """Retrieve and bin historical power usage for this device."""
        return None

    def build_cvxpy(self, n, dt, mpc_soc, mpc_soc_min_param):
        """Define CVXPY variables, constraints and rewards."""
        return [], 0, np.zeros(n)

    def update_values(self, n, dt, time_index, load_5min):
        """Update CVXPY parameters based on latest forecasts/state."""
        pass

    def get_results(self, dt):
        """Extract results from the solver."""
        return {}


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

    cleaned: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue

        load = OptionalLoad.from_dict(item)
        if load is None:
            continue

        cleaned.append(load.to_dict())

    return cleaned


def save_optional_loads(loads: list[dict[str, Any]]) -> None:
    cleaned: list[dict[str, Any]] = []
    for item in loads:
        if not isinstance(item, dict):
            continue

        load = OptionalLoad.from_dict(item)
        if load is None:
            continue

        cleaned.append(load.to_dict())

    path = _storage_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, indent=2)