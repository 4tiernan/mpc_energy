from energy_controller import ControlMode
import logging
import config_manager

logger = logging.getLogger(__name__)

class RBC():    
    def __init__(self, ha, ha_mqtt, plant, EC, buffer_percentage_remaining=35, max_discharge_rate = 15):
        self.ha = ha
        self.ha_mqtt = ha_mqtt
        self.plant = plant
        self.EC = EC
        
        self.MODES = [
            ControlMode.DISPATCH,
            ControlMode.EXPORT_ALL_SOLAR,
            ControlMode.EXPORT_EXCESS_SOLAR,
            ControlMode.SELF_CONSUMPTION
        ]

        self.feedIn_price = 0
        self.target_dispatch_price = 0
        self.buffer_percentage_remaining = buffer_percentage_remaining
        self.solar_kwh_forecast_remaining = 0
        self.kwh_energy_available = 0 # kWh of battery and solar available to use today
        self.kwh_required_remaining = self.plant.kwh_required_remaining(buffer_percentage=self.buffer_percentage_remaining)
        self.max_discharge_rate = max_discharge_rate
        self.hrs_of_discharge_available = 2
        self.MINIMUM_BATTERY_DISPATCH_PRICE = config_manager.battery_discharge_cost #minimum price that is worth dispatching the battery for
        self.working_mode = ControlMode.SELF_CONSUMPTION
        self.target_price_reduction_percentage = 10 # Percentage reduction of ideal sell price to sell at (Assumes the max price won't occour)

        self.last_control_mode = self.plant.get_plant_mode()

    def update_values(self, amber_data):
        self.plant.update_data()
        self.MINIMUM_BATTERY_DISPATCH_PRICE = config_manager.battery_discharge_cost
        self.feedIn_price = amber_data.feedIn_price
        self.solar_kwh_forecast_remaining = self.plant.solar_kw_remaining_today
        self.kwh_required_remaining = self.plant.kwh_required_remaining(buffer_percentage=self.buffer_percentage_remaining)
        self.kwh_required_till_sundown = self.plant.kwh_required_till_sundown(buffer_percentage=self.buffer_percentage_remaining)

        self.kwh_energy_available = self.plant.kwh_stored_available
        
        self.hrs_of_discharge_available = max((self.kwh_energy_available - self.kwh_required_remaining) / self.plant.max_export_power, 0) #constrain to not go negative

        self.target_dispatch_price = amber_data.feedIn_12hr_forecast_sorted[max(round(self.hrs_of_discharge_available*2),0)].price # get the number of 30 minute periods that the battery is allowed to discharge to
        self.target_dispatch_price = ((100-self.target_price_reduction_percentage)/100.0) * self.target_dispatch_price # Slightly reduce the target dispatch price to capture more events that are still valuable given forecast uncertanty 
        self.target_dispatch_price = round(max(self.target_dispatch_price, self.MINIMUM_BATTERY_DISPATCH_PRICE)) 
        #print(f"Discharge 30 minute windows: {self.hrs_of_discharge_available*2}")     

    def can_enter_mode(self, mode):
        if(mode == ControlMode.DISPATCH):
            return (self.feedIn_price >= self.target_dispatch_price and
                     self.kwh_energy_available > self.kwh_required_remaining + 1)
        
        elif(mode == ControlMode.EXPORT_ALL_SOLAR):
            return (self.solar_kwh_forecast_remaining + self.kwh_energy_available >= self.kwh_required_till_sundown + self.plant.kwh_till_full + 11 and
                     self.feedIn_price >= 2 and self.plant.solar_daytime)
        
        elif(mode == ControlMode.EXPORT_EXCESS_SOLAR):
            return (self.feedIn_price >= 0)
        
        elif(mode == ControlMode.SELF_CONSUMPTION):
            return True
        
        else:
            raise(f"Error, mode '{mode}' is unknown")
        
    def should_exit(self, mode):
        if(mode == ControlMode.DISPATCH):
            return (self.feedIn_price < self.target_dispatch_price or
                     self.kwh_energy_available <= self.kwh_required_remaining)
        
        elif(mode == ControlMode.EXPORT_ALL_SOLAR):
            return (self.solar_kwh_forecast_remaining + self.kwh_energy_available < self.kwh_required_till_sundown + self.plant.kwh_till_full + 10 or
                     self.feedIn_price < 2 or not self.plant.solar_daytime)
        
        elif(mode == ControlMode.EXPORT_EXCESS_SOLAR):
            return (self.feedIn_price < 0)
        
        elif(mode == ControlMode.SELF_CONSUMPTION): # No need to exit lowest mode unless another mode can be active
            return False
            
        else:
            raise(f"Error, mode '{mode}' is unknown")
        
    def select_mode(self):
        current_mode = self.working_mode

        # Check for higher priority modes that can be selected
        for mode in self.MODES:
            if current_mode is None or self.MODES.index(mode) <  self.MODES.index(current_mode):
                if(self.can_enter_mode(mode)):
                    return mode

        # Check current control mode still wants control
        if current_mode and not self.should_exit(current_mode):
            return current_mode
        
        # Fall back to best available mode
        for mode in self.MODES:
            if self.can_enter_mode(mode):
                return mode
        
        return None
    
    def run(self, amber_data):
        self.update_values(amber_data)
        selected_mode = self.select_mode()
        if(selected_mode == ControlMode.DISPATCH):
            self.EC.dispatch()
        elif(selected_mode == ControlMode.EXPORT_ALL_SOLAR):
            self.EC.export_all_solar()
        elif(selected_mode == ControlMode.EXPORT_EXCESS_SOLAR):
            self.EC.export_excess_solar()
        elif(selected_mode == ControlMode.SELF_CONSUMPTION):
            self.EC.self_consumption()
         

'''
from ha_api import HomeAssistantAPI
from amber_api import AmberAPI
import PlantControl
import ha_mqtt
from api_token_secrets import HA_URL, HA_TOKEN, AMBER_API_TOKEN, SITE_ID
amber = AmberAPI(AMBER_API_TOKEN, SITE_ID, errors=True)
amber_data = amber.get_data()
plant = PlantControl.Plant(HA_URL, HA_TOKEN, errors=True) 
ha = HomeAssistantAPI(
    base_url=HA_URL,
    token=HA_TOKEN,
    errors=True
)
rbc = RBC(ha, ha_mqtt, plant)
print(rbc.run(amber_data))
'''