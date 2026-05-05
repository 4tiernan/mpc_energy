from EV_chargers.EV_charger import EVCharger
from ha_api import HomeAssistantAPI
from mpc_logger import logger
import time

class TeslaAPICharger(EVCharger):
    """
    EV Charger implementation for Tesla vehicles using the Tesla API.
    """
    def __init__(
            self, 
            name: str, 
            ha: HomeAssistantAPI,
            
            plugged_in_entity_id: str,
            nominal_ac_voltage: float,
            min_charge_current: float,
            max_charge_current: float,

            power_entity_id: str,

            charge_current_entity_id: str,
            charge_enable_entity_id: str,
            charger_model: str,
            ):
        
        
        self.plugged_in_entity_id = plugged_in_entity_id
        self.nominal_ac_voltage = nominal_ac_voltage
        self.min_charge_current = min_charge_current
        self.max_charge_current = max_charge_current

        self.min_charge_power_kw = (self.nominal_ac_voltage * self.min_charge_current) / 1000.0
        self.max_charge_power_kw = (self.nominal_ac_voltage * self.max_charge_current) / 1000.0

        super().__init__(name, ha, self.min_charge_power_kw, self.max_charge_power_kw)

        self.power_entity_id = power_entity_id
        self.charge_current_entity_id = charge_current_entity_id
        self.charge_enable_entity_id = charge_enable_entity_id
        self.charger_model = charger_model

        self.last_control_entity_update_time = 0.0 # Timestamp of the last time we sent a control command to the charger, used to rate limit calls
        self.min_time_between_control_updates = 30.0 # Minimum time in seconds between control updates to avoid hitting the charger controls to frequently.

    def set_target_charge_rate(self, kw: float):
        """
        Sets the charging rate of the Tesla EV charger in kW using the Tesla API.
        """
        self.target_charge_rate = kw
    
    def update(self):
        """
        Update the charger state by fetching the latest data from Home Assistant and checking wheather a car is plugged in and adapting charge rate as needed.
        """
        car_plugged_in = self.ha.get_boolean_state(self.plugged_in_entity_id)

        if car_plugged_in:
            target_charge_current = round((self.target_charge_rate * 1000) / self.nominal_ac_voltage)

            if(target_charge_current < self.min_charge_current or target_charge_current > self.max_charge_current):
                logger.debug(f"Calculated target charge current {target_charge_current:.2f}A is out of bounds for charger {self.name}. Setting it within the {self.min_charge_current:.2f}-{self.max_charge_current:.2f}A range limits.")
            target_charge_current = max(self.min_charge_current, min(self.max_charge_current, target_charge_current))
            
            desired_switch_state = target_charge_current > 0
            desired_current_input_state = target_charge_current if target_charge_current > 0 else 0.0


        else:
            desired_switch_state = False
            desired_current_input_state = self.min_charge_current # Set to min charge current when not plugged in to avoid errors


        switch_entity_state = self.ha.get_boolean_state(self.charge_enable_entity_id)
        current_input_entity_state = self.ha.get_numeric_state(self.charge_current_entity_id)

        if((switch_entity_state != desired_switch_state or current_input_entity_state != desired_current_input_state) and (time.time() - self.last_control_entity_update_time) < self.min_time_between_control_updates):
            logger.debug(f"Warning: Rate limiting control updates for {self.name}. Desired switch state: {desired_switch_state}, current switch state: {switch_entity_state}, desired current input: {desired_current_input_state:.2f}A, current input state: {current_input_entity_state:.2f}A. Will attempt to update again in {(self.min_time_between_control_updates - (time.time() - self.last_control_entity_update_time)):.2f} seconds.")
            return

        if(switch_entity_state != desired_switch_state):
            self.ha.set_switch_state(self.charge_enable_entity_id, desired_switch_state)
            logger.debug(f"Set switch state for {self.name} to {desired_switch_state} as the car is currently plugged in and target charge rate is {self.target_charge_rate:.2f} kW.")
            self.last_control_entity_update_time = time.time()
        
        if(current_input_entity_state != desired_current_input_state):
            self.ha.set_number(self.charge_current_entity_id, desired_current_input_state)
            logger.debug(f"Set charge current for {self.name} to {desired_current_input_state:.2f} A as the car is currently plugged in and target charge rate is {self.target_charge_rate:.2f} kW.")
            self.last_control_entity_update_time = time.time()
        

