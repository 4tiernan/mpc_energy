from abc import ABC, abstractmethod
from ha_api import HomeAssistantAPI

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
    def set_charge_rate(self, kw: float):
        """
        Sets the charging rate of the EV charger in kW.
        This method should be overridden by specific charger implementations.
        """
        raise NotImplementedError("Subclasses must implement set_charge_rate")
    
    @abstractmethod    
    def update(self):
        """
        Update the charger state by fetching the latest data from Home Assistant and syncing with the Tesla API if needed.
        This is a placeholder implementation and should be replaced with actual API calls and logic.
        """
        raise NotImplementedError("Subclasses must implement update")