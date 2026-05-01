import json
import os
from typing import Any
from dataclasses import dataclass

DEFAULT_PATH = "/data/optional_loads.json"


def _storage_path() -> str:
    configured_path = os.environ.get("MPC_OPTIONAL_LOADS_PATH", DEFAULT_PATH)
    storage_dir = os.path.dirname(configured_path)
    if storage_dir and os.path.isdir(storage_dir):
        return configured_path

    # Fallback for local/dev runs where /data is not mounted.
    return os.path.join(os.path.dirname(__file__), "optional_loads.json")


@dataclass
class OptionalLoad:
    name: str
    power_entity_id: str
    plugged_in_entity_id: str = ""
    soc_entity_id: str = ""
    battery_capacity_kwh: float = 0.0
    max_charge_power_entity_id: str = ""
    min_charge_power_kw: float = 0.0
    min_soc: float = 0.0
    max_soc: float = 100.0
    charge_reward_cents_per_kwh: float = 0.0

    @classmethod
    def from_dict(cls, item: dict[str, Any]) -> "OptionalLoad | None":
        power_entity_id = str(item.get("power_entity_id", item.get("entity_id", ""))).strip()
        if not power_entity_id:
            return None
        name = str(item.get("name", power_entity_id)).strip() or power_entity_id
        return cls(
            name=name,
            power_entity_id=power_entity_id,
            plugged_in_entity_id=str(item.get("plugged_in_entity_id", "")).strip(),
            soc_entity_id=str(item.get("soc_entity_id", "")).strip(),
            battery_capacity_kwh=float(item.get("battery_capacity_kwh", 0.0) or 0.0),
            max_charge_power_entity_id=str(item.get("max_charge_power_entity_id", "")).strip(),
            min_charge_power_kw=float(item.get("min_charge_power_kw", 0.0) or 0.0),
            min_soc=float(item.get("min_soc", 0.0) or 0.0),
            max_soc=float(item.get("max_soc", 100.0) or 100.0),
            charge_reward_cents_per_kwh=float(item.get("charge_reward_cents_per_kwh", 0.0) or 0.0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "power_entity_id": self.power_entity_id,
            "plugged_in_entity_id": self.plugged_in_entity_id,
            "soc_entity_id": self.soc_entity_id,
            "battery_capacity_kwh": self.battery_capacity_kwh,
            "max_charge_power_entity_id": self.max_charge_power_entity_id,
            "min_charge_power_kw": self.min_charge_power_kw,
            "min_soc": self.min_soc,
            "max_soc": self.max_soc,
            "charge_reward_cents_per_kwh": self.charge_reward_cents_per_kwh,
        }


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