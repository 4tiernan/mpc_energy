from abc import ABC, abstractmethod
from ha_api import HomeAssistantAPI
from mpc_logger import logger
from typing import Any

charger_models = ["Tesla API", "SigEnergy AC Charger", "GoodWe"]

class EVCharger(ABC):
    """
    Base class for EV Chargers. 
    Specific charger models should inherit from this class.
    """
    def __init__(self, name: str, ha: HomeAssistantAPI, min_charge_power_kw: float, max_charge_power_kw: float):
        self.name = name
        self.ha: HomeAssistantAPI = ha
        self.min_charge_power_kw = min_charge_power_kw
        self.max_charge_power_kw = max_charge_power_kw
        self.target_charge_rate = 0.0 # Current target charge rate in kW

    @abstractmethod
    def set_target_charge_rate(self, kw: float):
        """
        Sets the charging rate of the EV charger in kW.
        This method should be overridden by specific charger implementations.
        """
        raise NotImplementedError("Subclasses must implement set_target_charge_rate")
    
    @abstractmethod
    def update_state(self):
        """
        Update the charger's internal state (like power limits) by fetching the latest data from Home Assistant.
        This should not perform any control actions.
        """
        raise NotImplementedError("Subclasses must implement update_state")

    @abstractmethod    
    def update(self):
        """
        Update the charger state by fetching the latest data from Home Assistant and syncing with the Tesla API if needed.
        This is a placeholder implementation and should be replaced with actual API calls and logic.
        """
        raise NotImplementedError("Subclasses must implement update")

def create_charger_instance(config: dict[str, Any], ha: HomeAssistantAPI) -> "EVCharger | None":
    """
    Factory function to create a specific EVCharger instance based on a configuration dictionary.
    """
    charger_model = config.get("charger_model", "")

    if charger_model == "Tesla API":
        from loads.EV_chargers.teslaAPI_charger import TeslaAPICharger
        return TeslaAPICharger(
            name=config.get("name", ""),
            ha=ha,
            plugged_in_entity_id=config.get("plugged_in_entity_id", ""),
            nominal_ac_voltage=float(config.get("nominal_ac_voltage", 230.0) or 230.0),
            min_charge_current=float(config.get("min_charge_current", 0.0) or 0.0),
            max_charge_current=float(config.get("max_charge_current", 0.0) or 0.0),
            power_entity_id=config.get("power_entity_id", ""),
            three_phase_available_entity_id=config.get("three_phase_available_entity_id", ""),
            charge_current_entity_id=config.get("charge_current_entity_id", ""),
            charge_enable_entity_id=config.get("charge_enable_entity_id", ""),
            charger_model=charger_model
        )
    elif charger_model == "SigEnergy AC Charger":
        logger.warning(f"Charger model '{charger_model}' is not yet implemented.")
        return None
    else:
        logger.warning(f"Unknown charger model '{charger_model}' for load '{config.get('name', 'Unknown')}'. Skipping charger instantiation.")
        return None

def init_chargers(opt_loads: list, ha: HomeAssistantAPI):
    """
    Iterates through optional loads and initializes chargers for EV loads.
    """
    from loads.EV_load import EVLoad
    for load in opt_loads:
        if isinstance(load, EVLoad):
            # Pass the configuration dict to separate charger init from the EVLoad instance
            charger = create_charger_instance(load.to_dict(), ha)
            if charger:
                load.set_charger(charger)