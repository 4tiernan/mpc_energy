import json
import os
from typing import Any

DEFAULT_PATH = "/data/optional_loads.json"


def _storage_path() -> str:
    configured_path = os.environ.get("MPC_OPTIONAL_LOADS_PATH", DEFAULT_PATH)
    storage_dir = os.path.dirname(configured_path)
    if storage_dir and os.path.isdir(storage_dir):
        return configured_path

    # Fallback for local/dev runs where /data is not mounted.
    return os.path.join(os.path.dirname(__file__), "optional_loads.json")


class OptionalLoad:
    def __init__(
        self,
        name: str,
        power_entity_id: str,
        load_type: str = "ev",
        plugged_in_entity_id: str = "",
        level_entity_id: str = "",
        capacity_kwh: float = 0.0,
        max_charge_power_entity_id: str = "",
        min_charge_power_kw: float = 0.0,
        min_limit: float = 0.0,
        max_limit: float = 100.0,
        charge_reward_cents_per_kwh: float = 0.0,
        volume_l: float = 0.0,
        temp_min: float = 0.0,
        temp_max: float = 0.0,
    ):
        # Configuration parameters
        self.name = name
        self.power_entity_id = power_entity_id
        self.load_type = load_type
        self.plugged_in_entity_id = plugged_in_entity_id
        self.level_entity_id = level_entity_id
        self.capacity_kwh = capacity_kwh
        self.max_charge_power_entity_id = max_charge_power_entity_id
        self.min_charge_power_kw = min_charge_power_kw
        self.min_limit = min_limit
        self.max_limit = max_limit
        self.charge_reward_cents_per_kwh = charge_reward_cents_per_kwh
        self.volume_l = volume_l
        self.temp_min = temp_min
        self.temp_max = temp_max

        # Real-time state attributes (manipulated data)
        self.is_plugged_in: bool = False
        self.current_power_kw: float = 0.0
        self.current_level_percent: float = 0.0
        self.max_charge_power_limit: float = 0.0

    @property
    def current_charge_kwh(self) -> float:
        """Returns the current energy level in kWh."""
        return (self.current_level_percent / 100.0) * self.capacity_kwh

    @property
    def charge_remaining_kwh(self) -> float:
        """Returns the energy required to reach the max target in kWh."""
        target_kwh = (self.max_limit / 100.0) * self.capacity_kwh
        return max(0.0, target_kwh - self.current_charge_kwh)

    def update_data(self, ha) -> None:
        """Collects and updates real-time data from Home Assistant."""
        self.current_power_kw = self._get_numeric(ha, self.power_entity_id)
        
        raw_level_val = self._get_numeric(ha, self.level_entity_id) if self.level_entity_id else 0.0
        
        # Handle thermal loads (Hot Water)
        if self.load_type == "hot_water" and self.volume_l > 0 and self.temp_max > self.temp_min:
            # Energy Capacity (kWh) = (Volume * 4.186 * deltaT) / 3600
            self.capacity_kwh = (self.volume_l * 4.186 * (self.temp_max - self.temp_min)) / 3600.0
            # Calculate level based on current temperature: % = (current_T - T_min) / (T_max - T_min)
            self.current_level_percent = min(max((raw_level_val - self.temp_min) / (self.temp_max - self.temp_min) * 100.0, 0.0), 100.0)
        elif self.level_entity_id:
            # Standard percentage based Level (EV/Battery)
            self.current_level_percent = min(max(raw_level_val, 0.0), 100.0)
        
        if self.plugged_in_entity_id:
            self.is_plugged_in = self._get_bool(ha, self.plugged_in_entity_id)
        else:
            self.is_plugged_in = True  # Assume always plugged in if no sensor provided
            
        self.max_charge_power_limit = self._get_numeric(ha, self.max_charge_power_entity_id)

    @classmethod
    def from_dict(cls, item: dict[str, Any]) -> "OptionalLoad | None":
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
            charge_reward_cents_per_kwh=float(item.get("charge_reward_cents_per_kwh", 0.0) or 0.0),
            volume_l=float(item.get("volume_l", 0.0) or 0.0),
            temp_min=float(item.get("temp_min", 0.0) or 0.0),
            temp_max=float(item.get("temp_max", 0.0) or 0.0),
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
            "charge_reward_cents_per_kwh": self.charge_reward_cents_per_kwh,
            "volume_l": self.volume_l,
            "temp_min": self.temp_min,
            "temp_max": self.temp_max,
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