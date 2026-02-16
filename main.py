import subprocess
import sys
import time
import datetime
import traceback
import logging
import colorlog
import config_manager
import const


# Create a color formatter
formatter = colorlog.ColoredFormatter(
    "%(log_color)s%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    log_colors={
        'DEBUG':    'cyan',
        'INFO':     'green',
        'WARNING':  'yellow',
        'ERROR':    'red',
        'CRITICAL': 'bold_red',
    }
)
# Create a handler
handler = logging.StreamHandler()
handler.setFormatter(formatter)

# Set up the logger
logger = colorlog.getLogger()
logger.addHandler(handler)
logger.setLevel(logging.INFO)


# Configure logging with timestamps without milliseconds
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"  # <- remove milliseconds
)
logger = logging.getLogger(__name__)


# Silence logger spam
logging.getLogger("ha_mqtt_discoverable").setLevel(logging.WARNING)
logging.getLogger("ha_mqtt_discoverable.sensors").setLevel(logging.WARNING)
logging.getLogger("matplotlib.font_manager").setLevel(logging.WARNING)

# Check to see if an amber site number has been set and print the available ones if not
if(config_manager.amber_site_id == ""):
    from amber_api import AmberAPI
    amber = AmberAPI(config_manager.amber_api_key, "")
    sites = amber.get_sites()
    string_data = ""
    for site in sites:
        available_channels = []
        for channel in site['channels']:
            available_channels.append(channel['type'])
        string_data = string_data + f"Site ID: {site['id']},  NMI: {site['nmi']}, Channels: {available_channels}"
    logger.error(f"Amber Site ID not selected, please copy the desired site number into the configuration tab:\n{string_data}")
    exit()

# HA APP Setup Notes:
# Proxmox CPU Type must be set to host not kvm64

# HA MQTT Python Lib: https://pypi.org/project/ha-mqtt-discoverable/
# nano /etc/systemd/system/energy-manager.service
# journalctl -u energy-manager -f
# journalctl -u energy-manager -n 10000 -f
# systemctl status energy-manager
# source venv/bin/activate (from within cd opt/energy-manager)
# nano /opt/energy-manager/run.sh

logger.info("Starting MPC Energy App")
started = False

def PrintError(e):
    logger.warning(f"Exception occoured: {e}")
    traceback.print_exc() # Prints the full traceback to the console
    logger.warning("Trying again after 30 seconds")
    time.sleep(30)

def ensure_remote_ems(): # Ensures the remote EMS switch is on provided the automatic control switch is on
    if(ha.get_state("input_select.automatic_control_mode")["state"] == "On"):
            ha.set_switch_state(config_manager.ha_ems_control_switch_entity_id, True)
            time.sleep(2) # delay to ensure the change has time to become effective


while(started == False):
    try:
        from RBC import RBC
        from MPC import MPC
        from energy_controller import EnergyController
        from ha_api import HomeAssistantAPI
        import ha_mqtt
        from amber_api import AmberAPI
        from PlantControl import Plant

        amber = AmberAPI(config_manager.amber_api_key, config_manager.amber_site_id, errors=True)
        #amber_data = amber.get_data()

        ha = HomeAssistantAPI(
            base_url=const.HA_API_URL,
            token=const.HA_TOKEN,
            errors=True
        )
        
        plant = Plant(ha) 

        
        ensure_remote_ems()
        

        ha_mqtt.controller_update_selector.set_state("Working")

        EC = EnergyController(
            ha=ha,
            ha_mqtt=ha_mqtt,
            plant=plant
        )

        rbc = RBC(
            ha=ha, 
            ha_mqtt=ha_mqtt,
            plant=plant, 
            EC=EC,
            buffer_percentage_remaining=35, # percentage to inflate predicted load consumption
        )

        mpc = MPC(
            ha=ha,
            plant=plant,
            EC=EC
        )     

        # Start Streamlit dashboard
        streamlit_proc = subprocess.Popen([
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "webserver.py",
            "--server.headless=true",
            "--server.port=8501",
            "--server.address=0.0.0.0",
            "--server.enableCORS=false",
            "--server.enableXsrfProtection=false",
            "--theme.base=light"
        ])


        #logger.info("Streamlit dashboard started")  

        started = True
    except Exception as e:
        PrintError(e)
        

start_time = time.time()
last_amber_update_timestamp = 0
automatic_control = True # var to keep track of whether the auto control switch is on

next_amber_update_timestamp = time.time() #time to run the next amber update
partial_update = False #Indicates wheather to do a full amber update or just the current prices (if only estimated prices)
last_amber_update_timestamp = time.time()
amber_data = amber.get_data(forecast_hrs=mpc.forecast_hrs)
mpc.run_optimisation(amber_data) # Get the latest optimisiation to plot on the dashboard
last_control_mode = ""

def determine_effective_price(amber_data):
    general_price = amber_data.general_price
    feedIn_price = amber_data.feedIn_price
    target_dispatch_price = rbc.target_dispatch_price
    remaining_solar_today = plant.solar_kw_remaining_today
    forecast_load_till_morning = rbc.kwh_required_remaining

    base_load = plant.get_base_load_estimate() # kW estimated base load
    solar_daytime = plant.solar_daytime # If producing more power than base load consider it during the solar day
    available_energy = max(remaining_solar_today-10, 0) + plant.kwh_stored_available # kWh of energy available right now
    energy_consumption_available = plant.kwh_till_full + plant.forecast_consumption_amount(forecast_till_time=datetime.time(18, 0, 0)) # kWh that can be used of the available solar

    effective_dispatch_price = max(target_dispatch_price, feedIn_price)

    if(general_price < 0):
        return general_price
    elif(solar_daytime): # Solar > base load estimate
        if(remaining_solar_today > energy_consumption_available): # There should be excess power that would be sold at the feed in price or wasted
            return max(feedIn_price, 0)
        elif(available_energy > forecast_load_till_morning): # Energy used will cut into feed in profits 
            return effective_dispatch_price
        else:
            return general_price
    else: # Not solar daytime
        if(plant.kwh_stored_available > forecast_load_till_morning): # More battery than required overnight, energy use will cut into feed in profits
            return effective_dispatch_price
        else:
            return general_price # default to the general price
        
def print_values(amber_data):
    logger.info("....")
    logger.info(f"Feed In: {amber_data.feedIn_price} c/kWh")
    logger.info(f"Max 12hr Feed In: {amber_data.feedIn_max_forecast_price} c/kWh")
    logger.info(f"General: {amber_data.general_price} c/kWh")
    
# Update HA MQTT sensors
def update_sensors(amber_data):
    rbc.update_values(amber_data=amber_data)
    ha_mqtt.max_feedIn_sensor.set_state(round(amber_data.feedIn_max_forecast_price))
    ha_mqtt.current_feedIn_sensor.set_state(round(amber_data.feedIn_price))
    ha_mqtt.current_general_price_sensor.set_state(round(amber_data.general_price))
    ha_mqtt.kwh_discharged_sensor.set_state(round(plant.kwh_till_full, 2))
    ha_mqtt.kwh_remaining_sensor.set_state(round(plant.kwh_stored_available, 2))
    ha_mqtt.target_discharge_sensor.set_state(round(rbc.target_dispatch_price))
    ha_mqtt.kwh_required_overnight_sensor.set_state(round(rbc.kwh_required_remaining, 2))    
    ha_mqtt.kwh_required_till_sundown_sensor.set_state(round(rbc.kwh_required_till_sundown, 2))
    ha_mqtt.amber_api_calls_remaining_sensor.set_state(amber.rate_limit_remaining)
    ha_mqtt.working_mode_sensor.set_state(EC.working_mode)
    logger.error("Make profit tracking sensors")
    profit = ha.get_numeric_state("sensor.daily_feed_in")
    cost = ha.get_numeric_state("sensor.daily_general_usage")
    ha_mqtt.system_state_sensor.set_state(EC.working_mode + f" {round(plant.grid_power,1)}@{amber_data.feedIn_price} c/kWh ${round(profit-cost,2)} profit")
    ha_mqtt.base_load_sensor.set_state(round(1000*plant.get_base_load_estimate(),2)) # converted to w from kW
    ha_mqtt.effective_price_sensor.set_state(determine_effective_price(amber_data)) 
    ha_mqtt.avg_daily_load_sensor.set_state(round(plant.avg_daily_load,2))

    
update_sensors(amber_data)
time.sleep(1)
logger.info("Configuration complete. Running")

# Code runs every 2 seconds (to reduce cpu usage)
def main_loop_code():
    global automatic_control, next_amber_update_timestamp, partial_update, amber_data, last_control_mode

    ensure_remote_ems() # Check Remote EMS switch is active

    if(time.time() >= next_amber_update_timestamp):
        if(partial_update):
            amber_data = amber.get_data(partial_update=True, forecast_hrs=mpc.forecast_hrs)
        else:
            amber_data = amber.get_data(forecast_hrs=mpc.forecast_hrs)

        ha_mqtt.estimated_price_status_sensor.set_state(int(amber_data.prices_estimated))

        if(amber_data.prices_estimated): # If prices are estimated, don't use them
            seconds_till_next_update = 5
            partial_update = True # Make the next update a partial one
        else: # If prices are real, use them
            partial_update = False
            real_price_offset = 30 # seconds after the period begins when the real price starts
            now_datetime = datetime.datetime.now()
            seconds_till_next_update = 300 - ((now_datetime.minute * 60 + now_datetime.second) % 300) + real_price_offset

        next_amber_update_timestamp = time.time() + seconds_till_next_update #update the time here before running MPC to ensure more accurate timings
        

        if(not amber_data.prices_estimated): #If the prices are real
            print_values(amber_data) # Print the new latest prices
            
            # Only run MPC every price update
            if(ha.get_state("input_select.automatic_control_mode")["state"] == "On" and ha_mqtt.energy_controller_selector.state == "MPC"):
                automatic_control = True
                mpc.run(amber_data)
                EC.run(amber_data=amber_data) 
                logger.info(f"MPC ran")
            else:
                mpc.run_optimisation(amber_data) # run the optimisation at each time step regardless 
        
        logger.info(f"Partial Update: {partial_update}")
        logger.info(f"Seconds till next update: {round(next_amber_update_timestamp - time.time())}")
        
        

    # If auto control is on, run the energy controller (every 2 seconds as we need to keep track of some things)
    if(ha.get_state("input_select.automatic_control_mode")["state"] == "On"):
        EC.run(amber_data=amber_data)
        automatic_control = True
        if(ha_mqtt.energy_controller_selector.state == "RBC"):
            rbc.run(amber_data) # RBC needs to run every 2 seconds
            last_control_mode = ha_mqtt.energy_controller_selector.state
        
        # If the MPC selector was selected, run MPC before the next price update
        if(last_control_mode != ha_mqtt.energy_controller_selector.state and ha_mqtt.energy_controller_selector.state == "MPC"):
            mpc.run(amber_data)
            last_control_mode = ha_mqtt.energy_controller_selector.state
         
    update_sensors(amber_data)


    # If Auto control is off, send a notification warning so
    if(ha.get_state("input_select.automatic_control_mode")["state"] != "On"):
        if(automatic_control == True):
            #EC.self_consumption()
            automatic_control = False
            logger.warning(f"Automatic Control turned off.")
            ha.send_notification(f"Automatic Control turned off", "Self Consuming", "mobile_app_pixel_10_pro")

    # If Auto control has been TURNED on, print a msg and reset flag
    elif(ha.get_state("input_select.automatic_control_mode")["state"] == "On" and automatic_control == False):
        automatic_control = True
        last_control_mode = "" # Reset flag so the approprate controller takes over
        logger.warning(f"Automatic Control turned on.")
                
            
    
while True:
    try:
        if(ha_mqtt.controller_update_selector.state == "Update"):
            logger.error("Update Commanded, exiting")
            break
        
        main_loop_code()
        time.sleep(2)

        ha_mqtt.alive_time_sensor.set_state(round(time.time()-start_time,1))

    except KeyboardInterrupt:
        logger.error("Keyboard Interrupt, Shutting down...")
        streamlit_proc.terminate()
        break
    
    except Exception as e:
        PrintError(e)

    