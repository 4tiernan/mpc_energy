import logging
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
import datetime
import time

from .const import DEFAULT_NAME, PlantEntityReferences
from .amber_api import AmberAPI
from .ha_entity_helper import HAEntityHelper
from .PlantControl import Plant
from .energy_controller import EnergyController
from .RBC import RBC
from .MPC import MPC

_LOGGER = logging.getLogger(__name__)


class MPCCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(
            hass,
            _LOGGER,
            name=DEFAULT_NAME,
            update_interval=datetime.timedelta(seconds=2),
        )
        self.hass = hass
        self.entry = entry

        # Initalise Sub Systems
        # Amber
        self.amber = AmberAPI(
            api_token=self.entry.data[PlantEntityReferences.AMBER_API_KEY],
            site_id=self.entry.data[PlantEntityReferences.AMBER_API_SITE_ID],
        )

        self.ha_helper = HAEntityHelper(
            hass=self.hass,
            entry=self.entry,
        )

        self.plant = Plant(self.ha)

        self.ec = EnergyController(
            ha_helper=self.ha_helper,
            plant=self.plant
        )

        self.rbc = RBC(
            ha_helper=self.ha_helper, 
            plant=self.plant, 
            ec=self.ec
        )

        self.mpc = MPC(
            ha_helper=self.ha_helper,
            plant=self.plant,
            ec=self.ec
        )

        self.start_time = time.time()

        self.last_amber_update_timestamp = 0
        self.automatic_control = True # var to keep track of whether the auto control switch is on

        self.next_amber_update_timestamp = time.time() #time to run the next amber update
        self.partial_update = False #Indicates wheather to do a full amber update or just the current prices (if only estimated prices)
        self.last_amber_update_timestamp = time.time()
        self.amber_data = self.amber.get_data(forecast_hrs=self.mpc.forecast_hrs)
        self.mpc.run_optimisation(self.amber_data) # Get the latest optimisiation to plot on the dashboard
        self.last_control_mode = ""


    async def _async_update_data(self):
        #battery_power_state = self.ha_helper.get_history(PlantEntityReferences.BATTERY_POWER, as_type=float)

        self.main_loop()

        return self.update_sensors()
    

    # Update HA sensors
    def update_sensors(self):
        output = {
            "effective_price": 5.232,
            "max_feedin_price": round(self.amber_data.feedIn_max_forecast_price),
            "feedin_price": round(self.amber_data.feedIn_price),
            "general_price": round(self.amber_data.general_price),
            "working_mode": self.ec.working_mode,
            "alive_time": round(time.time()-self.start_time,1)
        }
        return output
    
    def main_loop(self):
        #ensure_remote_ems() # Check Remote EMS switch is active
        if(time.time() >= self.next_amber_update_timestamp):
            if(self.partial_update):
                self.amber_data = self.amber.get_data(partial_update=True, forecast_hrs=self.mpc.forecast_hrs)
            else:
                self.amber_data = self.amber.get_data(forecast_hrs=self.mpc.forecast_hrs)

            if(self.amber_data.prices_estimated): # If prices are estimated, don't use them
                seconds_till_next_update = 5
                self.partial_update = True # Make the next update a partial one
            else: # If prices are real, use them
                self.partial_update = False
                real_price_offset = 30 # seconds after the period begins when the real price starts
                now_datetime = datetime.datetime.now()
                seconds_till_next_update = 300 - ((now_datetime.minute * 60 + now_datetime.second) % 300) + real_price_offset

            self.next_amber_update_timestamp = time.time() + seconds_till_next_update #update the time here before running MPC to ensure more accurate timings
            

            if(not self.amber_data.prices_estimated): #If the prices are real
                #print_values(amber_data) # Print the new latest prices
                
                # Only run MPC every price update
                #if(ha.get_state("input_select.automatic_control_mode")["state"] == "On" and ha_mqtt.energy_controller_selector.state == "MPC"):
                if(True):
                    self.automatic_control = True
                    self.mpc.run(self.amber_data)
                    self.ec.run(amber_data=self.amber_data) 
                    print(f"MPC ran")
                else:
                    mpc.run_optimisation(amber_data) # run the optimisation at each time step regardless 
            
            print(f"Partial Update: {self.partial_update}")
            print(f"Seconds till next update: {round(self.next_amber_update_timestamp - time.time())}")
            
            

        # If auto control is on, run the energy controller (every 2 seconds as we need to keep track of some things)
        #if(ha.get_state("input_select.automatic_control_mode")["state"] == "On"):
        if(True):
            self.ec.run(amber_data=self.amber_data)
            automatic_control = True
            #if(ha_mqtt.energy_controller_selector.state == "RBC"):
            if(False):
                self.rbc.run(self.amber_data) # RBC needs to run every 2 seconds
                self.last_control_mode = ha_mqtt.energy_controller_selector.state
            
            # If the MPC selector was selected, run MPC before the next price update
            #if(last_control_mode != ha_mqtt.energy_controller_selector.state and ha_mqtt.energy_controller_selector.state == "MPC"):
            if(False):
                self.mpc.run(amber_data)
                self.last_control_mode = ha_mqtt.energy_controller_selector.state
            

        # If Auto control is off, send a notification warning so
        #if(ha.get_state("input_select.automatic_control_mode")["state"] != "On"):
        #    if(automatic_control == True):
        #        #EC.self_consumption()
        #        automatic_control = False
        #        print(f"Automatic Control turned off.")
        #        ha.send_notification(f"Automatic Control turned off", "Self Consuming", "mobile_app_pixel_10_pro")

        # If Auto control has been TURNED on, print a msg and reset flag
        #elif(ha.get_state("input_select.automatic_control_mode")["state"] == "On" and automatic_control == False):
        #    automatic_control = True
        #    last_control_mode = "" # Reset flag so the approprate controller takes over
        #    print(f"Automatic Control turned on.")
