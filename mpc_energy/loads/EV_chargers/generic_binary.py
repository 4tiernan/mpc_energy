from loads.EV_chargers.EV_charger import EVCharger
from mpc_logger import logger

class GenericBinaryCharger(EVCharger):
    """
    A generic EV charger implementation for binary (On/Off) chargers.
    It calculates power based on nominal voltage and rated current.
    """
    def __init__(self, name, ha, switch_entity_id, nominal_voltage, rated_current, debias_load, plugged_in_entity_id=None, power_entity_id=None):
        self.switch_entity_id = switch_entity_id
        self.plugged_in_entity_id = plugged_in_entity_id
        self.power_entity_id = power_entity_id
        self.nominal_voltage = float(nominal_voltage)
        self.rated_current = float(rated_current)
        
        # Power (kW) = (V * I) / 1000
        self.nominal_power = (self.nominal_voltage * self.rated_current) / 1000.0
        
        super().__init__(name, ha, self.nominal_power, self.nominal_power, debias_load)
        
        self.state = "off"
        self.current_charge_rate_kw = 0.0        
        self.car_plugged_in = True

    def update_state(self):
        """
        Update the charger's internal state. 
        Binary chargers typically don't have complex internal states to sync.
        """
        pass

    def update(self):
        """Update charger state from Home Assistant."""
        try:
            if self.plugged_in_entity_id:
                self.car_plugged_in = self.ha.get_boolean_state(self.plugged_in_entity_id)

            if self.power_entity_id:
                self.current_charge_rate_kw = self.ha.get_numeric_state(self.power_entity_id)

            state_payload = self.ha.get_state(self.switch_entity_id)
            if isinstance(state_payload, dict):
                self.state = state_payload.get("state", "off").lower()
            else:
                self.state = "off"
            
            self.current_charge_rate_kw = self.nominal_power if self.state == "on" else 0.0
        except Exception as e:
            logger.error(f"Failed to update Generic Binary Charger '{self.name}': {e}")

    def set_target_charge_rate(self, kw: float, charging_mode: str):
        """
        Set the charge rate. Since this is a binary charger, any rate > 0 
        turns the switch ON, and a rate of 0 turns it OFF.
        """
        if kw > 0.05: # Use a small threshold to avoid floating point issues
            if self.state != "on":
                logger.info(f"Generic Binary Charger '{self.name}': Setting charge rate to {self.nominal_power:.2f} kW, ({kw:.2f} kW requested) (Switch ON)")
                try:
                    self.ha.set_switch_state(self.switch_entity_id, True)
                    self.state = "on"
                    self.target_charge_rate = self.nominal_power
                except Exception as e:
                    logger.error(f"Error turning ON Generic Binary Charger '{self.name}': {e}")
        else:
            if self.state != "off":
                logger.info(f"Generic Binary Charger '{self.name}': Setting charge rate to 0.00 kW, ({kw:.2f} kW requested) (Switch OFF)")
                try:
                    self.ha.set_switch_state(self.switch_entity_id, False)
                    self.state = "off"
                    self.target_charge_rate = 0.0
                except Exception as e:
                    logger.error(f"Error turning OFF Generic Binary Charger '{self.name}': {e}")

    def turn_off(self):
        """Stop charging."""
        self.set_target_charge_rate(0, None)
