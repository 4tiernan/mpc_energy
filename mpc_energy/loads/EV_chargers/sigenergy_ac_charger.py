from loads.EV_chargers.EV_charger import EVCharger
from loads.EV_load import EVLoad
from ha_api import HomeAssistantAPI
from mpc_logger import logger
import time

class SigEnergyACCharger(EVCharger):
    """
    EV Charger implementation for SigEnergy AC chargers.
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
            three_phase_available: bool,

            charge_current_entity_id: str,
            charge_enable_entity_id: str,
            charger_model: str,
            debias_load: bool
            ):
        
        
        self.plugged_in_entity_id = plugged_in_entity_id
        self.nominal_ac_voltage = nominal_ac_voltage
        self.min_charge_current = min_charge_current
        self.max_charge_current = max_charge_current

        self.available_phases = 3 if three_phase_available else 1
        self.min_charge_power_kw = self.available_phases * (self.nominal_ac_voltage * self.min_charge_current) / 1000.0
        self.max_charge_power_kw = self.available_phases * (self.nominal_ac_voltage * self.max_charge_current) / 1000.0

        super().__init__(name, ha, self.min_charge_power_kw, self.max_charge_power_kw, debias_load)

        self.three_phase_available = three_phase_available
        self.power_entity_id = power_entity_id
        self.charge_current_entity_id = charge_current_entity_id
        self.charge_enable_entity_id = charge_enable_entity_id
        self.charger_model = charger_model

        self.last_control_entity_update_time = 0.0 # Timestamp of the last time we sent a control command to the charger, used to rate limit calls
        self.min_time_between_control_updates = 30.0 # Minimum time in seconds between control updates to avoid hitting the charger controls to frequently.

    def update_state(self):
        """
        Update the charger state by fetching the latest data from Home Assistant and checking whether a car is plugged in and adapting power limits.
        """
        self.car_plugged_in = self.ha.get_boolean_state(self.plugged_in_entity_id)

        self.available_phases = 3 if self.three_phase_available else 1

        self.min_charge_power_kw = (self.available_phases * self.nominal_ac_voltage * self.min_charge_current) / 1000.0
        self.max_charge_power_kw = (self.available_phases * self.nominal_ac_voltage * self.max_charge_current) / 1000.0

    def update(self):
        """
        Update the charger state by fetching the latest data from Home Assistant and checking wheather a car is plugged in and adapting charge rate as needed.
        """
        self.update_state()

        if self.car_plugged_in and self.target_charge_rate is not None:
            if(self.target_charge_rate != 0):
                target_charge_current = int((self.target_charge_rate * 1000) / (self.available_phases * self.nominal_ac_voltage))
            else: 
                target_charge_current = self.min_charge_current # Set to min charge current when target charge rate is 0 to avoid errors with some chargers when trying to set 0A charge current. 

            if(target_charge_current < self.min_charge_current or target_charge_current > self.max_charge_current):
                logger.debug(f"Calculated target charge current {target_charge_current:.2f}A is out of bounds for charger {self.name}. Setting it within the {self.min_charge_current:.2f}-{self.max_charge_current:.2f}A range limits.")
            target_charge_current = max(self.min_charge_current, min(self.max_charge_current, target_charge_current))
            
            desired_switch_state = self.target_charge_rate > 0
            desired_current_input_state = target_charge_current if target_charge_current > 0 else 0.0


        else:
            desired_switch_state = False
            desired_current_input_state = self.min_charge_current # Set to min charge current when not plugged in to avoid errors

        if(self.charging_mode != EVLoad.EV_MODE_DISABLED):
            switch_entity_state = self.ha.get_boolean_state(self.charge_enable_entity_id)
            current_input_entity_state = self.ha.get_numeric_state(self.charge_current_entity_id)

            if((switch_entity_state != desired_switch_state or current_input_entity_state != desired_current_input_state) and (time.time() - self.last_control_entity_update_time) < self.min_time_between_control_updates):
                logger.debug(f"Warning: Rate limiting control updates for {self.name}. Desired switch state: {desired_switch_state}, current switch state: {switch_entity_state}, desired current input: {desired_current_input_state:.2f}A, current input state: {current_input_entity_state:.2f}A. Will attempt to update again in {(self.min_time_between_control_updates - (time.time() - self.last_control_entity_update_time)):.2f} seconds.")
                return

            if(switch_entity_state != desired_switch_state):
                self.ha.set_switch_state(self.charge_enable_entity_id, desired_switch_state)
                logger.debug(f"Set switch state for {self.name} to {desired_switch_state} from {switch_entity_state} (Plugged in: {self.car_plugged_in}, Target: {self.target_charge_rate:.2f} kW)")
                self.last_control_entity_update_time = time.time()
            
            if(current_input_entity_state != desired_current_input_state):
                self.ha.set_number(self.charge_current_entity_id, desired_current_input_state)
                logger.debug(f"Set charge current for {self.name} to {desired_current_input_state:.2f} A from {current_input_entity_state:.2f} A. (Plugged in: {self.car_plugged_in}, Target: {self.target_charge_rate:.2f} kW)")
                self.last_control_entity_update_time = time.time()
        
