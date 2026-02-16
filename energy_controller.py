from enum import Enum
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

class ControlMode(Enum):
    SELF_CONSUMPTION = "Self Consumption"
    EXPORT_EXCESS_SOLAR = "Exporting Excess Solar"
    EXPORT_ALL_SOLAR = "Exporting All Solar"
    DISPATCH = "Dispatching"
    GRID_IMPORT = "Grid Import"
    SOLAR_TO_LOAD = "Solar To Load"

class EnergyController():
    def __init__(self, ha, ha_mqtt, plant):
        self.ha = ha
        self.ha_mqtt = ha_mqtt
        self.plant = plant

        self.working_mode = ControlMode.SELF_CONSUMPTION.value
        self.last_working_mode = None

        #Self consume on startup for saftey if auto control on
        if(ha.get_state("input_select.automatic_control_mode")["state"] == "On"):
            self.self_consumption()
                
    def dispatch(self, grid_export_limit=None):
        if(grid_export_limit == None):
            grid_export_limit = self.plant.max_export_power
        else:
            grid_export_limit = min(max(grid_export_limit, 0), self.plant.max_export_power)

        self.working_mode = ControlMode.DISPATCH.value
        self.plant.check_control_limits(
            working_mode=self.working_mode,
            control_mode="Command Discharging (PV First)",
            discharge=self.plant.max_discharge_power,
            charge=0,
            pv=self.plant.max_pv_power,
            grid_export=grid_export_limit,
            grid_import=0)
        
    def export_all_solar(self):
        self.working_mode = ControlMode.EXPORT_ALL_SOLAR.value

        solar_buffer = 2 # Buffer to ensure load is covered by battery or solar
        if(self.plant.load_power + solar_buffer < self.plant.solar_kw): # Let the battery charge with excess DC power available
            self.plant.check_control_limits(
                working_mode=self.working_mode,
                control_mode="Command Discharging (PV First)",
                discharge=0,
                charge=self.plant.max_charge_power,
                pv=self.plant.max_pv_power,
                grid_export=self.plant.max_export_power,
                grid_import=0)
        else: # Make sure the battery supplies the load if solar power is minimal
            self.plant.check_control_limits(
                working_mode=self.working_mode,
                control_mode="Command Charging (PV First)",
                discharge=self.plant.max_discharge_power,
                charge=0,
                pv=self.plant.max_pv_power,
                grid_export=self.plant.max_export_power,
                grid_import=0)

    def export_excess_solar(self, battery_charge_limit=None):
        if(battery_charge_limit == None):
            battery_charge_limit = self.plant.max_charge_power
        else:
            battery_charge_limit = min(max(battery_charge_limit, 0), self.plant.max_charge_power)

        self.working_mode = ControlMode.EXPORT_EXCESS_SOLAR.value
        self.plant.check_control_limits(
            working_mode=self.working_mode,
            control_mode="Command Charging (PV First)",
            discharge=self.plant.max_discharge_power,
            charge=battery_charge_limit,
            pv=self.plant.max_pv_power,
            grid_export=self.plant.max_export_power,
            grid_import=0)
        
    def solar_to_load(self):
        self.working_mode = ControlMode.SOLAR_TO_LOAD.value
        self.plant.check_control_limits(
            working_mode=self.working_mode,
            control_mode="Command Charging (PV First)",
            discharge=self.plant.max_discharge_power,
            charge=0,
            pv=self.plant.max_pv_power,
            grid_export=0,
            grid_import=0)
        
    def import_power(self, battery_charge_limit = None, pv_limit = None):
        if(battery_charge_limit == None):
            battery_charge_limit = self.plant.max_charge_power
        else:
            battery_charge_limit = min(max(battery_charge_limit, 0), self.plant.max_charge_power)

        if(pv_limit == None):
            pv_limit = self.plant.max_pv_power
        else:
            pv_limit = min(max(pv_limit, 0), self.plant.max_pv_power)

        self.working_mode = ControlMode.GRID_IMPORT.value
        self.plant.check_control_limits(
            working_mode=self.working_mode,
            control_mode="Command Charging (PV First)",
            discharge=self.plant.max_discharge_power,
            charge=battery_charge_limit,
            pv=pv_limit,
            grid_export=0,
            grid_import=self.plant.max_import_power)


    def self_consumption(self, pv_limit = None):
        if(pv_limit == None):
            pv_limit = self.plant.max_pv_power
        self.working_mode = ControlMode.SELF_CONSUMPTION.value
        self.plant.check_control_limits(
            working_mode=self.working_mode,
            control_mode="Maximum Self Consumption",
            discharge=self.plant.max_discharge_power,
            charge=self.plant.max_charge_power,
            pv=pv_limit,
            grid_export=0,
            grid_import=0)
    
    def run(self, amber_data):
        self.last_working_mode = self.working_mode
        self.mainain_control_mode()

    def mainain_control_mode(self): # Maintain the current control mode (mainly export all solar)
        self.plant.update_data()
        if(self.working_mode == ControlMode.EXPORT_ALL_SOLAR.value):
            self.export_all_solar()
                