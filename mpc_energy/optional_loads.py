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


def load_optional_loads() -> list[dict[str, str]]:
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

    cleaned: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue

        entity_id = str(item.get("entity_id", "")).strip()
        if not entity_id:
            continue

        name = str(item.get("name", entity_id)).strip() or entity_id
        cleaned.append({"name": name, "entity_id": entity_id})

    return cleaned


def save_optional_loads(loads: list[dict[str, Any]]) -> None:
    cleaned: list[dict[str, str]] = []
    for item in loads:
        if not isinstance(item, dict):
            continue

        entity_id = str(item.get("entity_id", "")).strip()
        if not entity_id:
            continue

        name = str(item.get("name", entity_id)).strip() or entity_id
        cleaned.append({"name": name, "entity_id": entity_id})

    path = _storage_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, indent=2)