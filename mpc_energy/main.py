import subprocess
import sys
import time
import datetime
import traceback
import config_manager
import const
from mpc_logger import logger

app_start_timestamp = time.time()
def start_timer():
    global start_time
    start_time = time.time()
    return start_time

def elapsed_time(code_block_name="Code Block"):
    global start_time
    elapsed = time.time() - start_time
    logger.info(f"{code_block_name} took {round(elapsed, 2)} seconds")
    return elapsed

if(not config_manager.accepted_risks):
    logger.error("You must toggle the accept risks switch to acknowledge the risks associated with use of this software before being able to use the app.")
    exit()

# Check to see if an amber site number has been set and print the available ones if not
if(config_manager.amber_site_id == ""):
    from amber_api import AmberAPI
    amber = AmberAPI(config_manager.amber_api_key, "")
    sites = amber.get_sites()
    if(not sites):
        logger.error("No sites were found, amber may not have transfered your connection yet. This can take approximatly 4 days (https://help.amber.com.au/hc/en-us/articles/34942303478797-Solar-and-Battery-Onboarding-What-to-Expect-When-Enrolling-to-SmartShift). Please try again later.")
        exit()
        
    string_data = ""
    #logger.info(sites)    
    for site in sites:
        available_channels = []
        for channel in site['channels']:
            available_channels.append(channel['type'])
        string_data = string_data + f"Site ID: {site['id']},  NMI: {site['nmi']}, Channels: {available_channels}"
    logger.warning(f"Amber Site ID not selected, please copy the desired site id into the configuration tab:\n({string_data})")
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

logger.info("------------------------  Starting MPC Energy App  ------------------------")
started = False

def PrintError(e):
    logger.warning(f"Exception occoured: {e}")
    traceback.print_exc() # Prints the full traceback to the console
    logger.warning("Trying again after 30 seconds")
    time.sleep(30)


while(started == False):
    try:
        from RBC import RBC
        from MPC import MPC
        from energy_controller import EnergyController
        from ha_api import HomeAssistantAPI
        import ha_mqtt
        from amber_api import AmberAPI
        from PlantControl import Plant
        from control_mode_override import ControlModeOverrideManager

        ha = HomeAssistantAPI(
            base_url=const.HA_API_URL,
            token=const.HA_TOKEN,
        )

        
        amber = AmberAPI(
            config_manager.amber_api_key,
            config_manager.amber_site_id,
            local_tz=ha.local_tz,
            demand_price=config_manager.amber_demand_price,
            errors=True
        )
        
        plant = Plant(ha) 
        
        EC = EnergyController(
            ha=ha,
            ha_mqtt=ha_mqtt,
            plant=plant
        )

        control_mode_override_manager = ControlModeOverrideManager(ha_mqtt=ha_mqtt, energy_controller=EC, plant=plant)

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
            EC=EC, 
            local_tz=ha.local_tz,
            demand_tarrif=amber.demand_tarrif
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
last_control_mode = ""
        
sensor_state_cache = {}

def set_sensor_if_changed(sensor, value):
    cache_key = id(sensor)
    if sensor_state_cache.get(cache_key) != value:
        sensor.set_state(value)
        sensor_state_cache[cache_key] = value   
    
# Update HA MQTT sensors
def update_sensors(amber_data):
    rbc.update_values(amber_data=amber_data)

    set_sensor_if_changed(ha_mqtt.max_feedIn_sensor, round(amber_data.feedIn_max_forecast_price))
    set_sensor_if_changed(ha_mqtt.current_feedIn_sensor, round(amber_data.feedIn_price))
    set_sensor_if_changed(ha_mqtt.current_general_price_sensor, round(amber_data.general_price))
    set_sensor_if_changed(ha_mqtt.kwh_discharged_sensor, round(plant.kwh_till_full, 2))
    set_sensor_if_changed(ha_mqtt.kwh_remaining_sensor, round(plant.kwh_stored_available, 2))
    set_sensor_if_changed(ha_mqtt.target_discharge_sensor, round(rbc.target_dispatch_price))
    set_sensor_if_changed(ha_mqtt.kwh_required_overnight_sensor, round(rbc.kwh_required_remaining, 2))    
    set_sensor_if_changed(ha_mqtt.kwh_required_till_sundown_sensor, round(rbc.kwh_required_till_sundown, 2))
    set_sensor_if_changed(ha_mqtt.amber_api_calls_remaining_sensor, amber.rate_limit_remaining)
    set_sensor_if_changed(ha_mqtt.working_mode_sensor, EC.working_mode)

    set_sensor_if_changed(ha_mqtt.import_cost_sensor, round(plant.daily_import_cost, 2))
    set_sensor_if_changed(ha_mqtt.export_profit_sensor, round(plant.daily_export_profit, 2))
    set_sensor_if_changed(ha_mqtt.net_profit_sensor, round(plant.daily_net_profit, 2))
    set_sensor_if_changed(ha_mqtt.profit_remaining_today_sensor, round(mpc.profit_remaining_today, 2))
    set_sensor_if_changed(ha_mqtt.profit_tomorrow_sensor, round(mpc.profit_tomorrow, 2))

    if(plant.grid_power < 0):
        price = amber_data.feedIn_price
        grid_status = "E"
    else:
        price = amber_data.general_price
        grid_status = "I"
    
    set_sensor_if_changed(ha_mqtt.system_state_sensor, EC.working_mode + f" {round(abs(plant.grid_power),1)}{grid_status}@{price} c/kWh ${round(plant.daily_net_profit,2)} profit")
    set_sensor_if_changed(ha_mqtt.base_load_sensor, round(1000*plant.get_base_load_estimate(),2)) # converted to w from kW
    set_sensor_if_changed(ha_mqtt.effective_price_sensor, round(mpc.current_effective_price*100)) 
    set_sensor_if_changed(ha_mqtt.avg_daily_load_sensor, round(plant.avg_daily_load,2))

def run_controller(price_update=False):
    global automatic_control, last_control_mode
    # If Auto control has been TURNED on, print a msg and reset flag
    selected_controller = ha_mqtt.energy_controller_selector.state

    if(control_mode_override_manager.run(amber_data)): # If the user selects manual control, don't allow another controller to run.
        last_control_mode = "Manual Override"
        mpc.run_optimisation(amber_data) # Run the MPC optimisation each time the price updates to keep the plot updated
        return

    if(ha_mqtt.automatic_control_switch.state == True):
        if(automatic_control == False):
            automatic_control = True
            last_control_mode = "" # Reset flag so the approprate controller takes over
            logger.warning(f"Automatic Control turned on.")

        if(selected_controller == "MPC"):
            if(last_control_mode != selected_controller or price_update == True):
                mpc.run(amber_data) # Run the MPC Controller if the price updates (every 5 min) or if it was just selected as the new controller

        elif(selected_controller == "RBC"):
            rbc.run(amber_data) # RBC needs to run every loop

        else: # Selected Controller must be safe mode
            EC.self_consumption()

        if(last_control_mode != selected_controller and last_control_mode != "" and automatic_control == True):
            logger.warning(f"Controller changed from {last_control_mode} to {selected_controller}")
            
        last_control_mode = selected_controller # Reset the controller tracker
 
        # If auto control is on, run the energy controller and RBC (every 2 seconds as we need to keep track of some things)
        EC.run(amber_data=amber_data)

    else: # Automatic Control Turned off
        if(automatic_control == True):
            #EC.self_consumption()
            automatic_control = False
            logger.warning(f"Automatic Control turned off.")

    if(price_update and (selected_controller != "MPC" or automatic_control == False)):
        mpc.run_optimisation(amber_data) # Run the MPC optimisation each time the price updates to keep the plot updated if the mpc.ran() function wasn't called


logger.info("Configuration complete. Running")

# Code runs every 10 seconds (to reduce cpu usage)
def main_loop_code():
    global automatic_control, next_amber_update_timestamp, partial_update, amber_data, last_control_mode
    plant.update_data() # Update the plant data once for everything else to use.

    if(time.time() >= next_amber_update_timestamp):
        if(partial_update):
            amber_data = amber.get_data(partial_update=True, forecast_hrs=mpc.forecast_hrs)
        else:
            amber_data = amber.get_data(forecast_hrs=mpc.forecast_hrs)

        set_sensor_if_changed(ha_mqtt.estimated_price_status_sensor, int(amber_data.prices_estimated))

        if(amber_data.prices_estimated): # If prices are estimated, don't use them
            seconds_till_next_update = 5
            partial_update = True # Make the next update a partial one
            logger.info(f"Prices are estimated, running partial update without price update. Will update prices in {seconds_till_next_update} seconds.")
        else: # If prices are real, use them
            partial_update = False
            real_price_offset = 30 # seconds after the period begins when the real price starts
            now_datetime = datetime.datetime.now()
            seconds_till_next_update = 300 - ((now_datetime.minute * 60 + now_datetime.second) % 300) + real_price_offset

        next_amber_update_timestamp = time.time() + seconds_till_next_update #update the time here before running MPC to ensure more accurate timings
        

        if(not amber_data.prices_estimated): #If the prices are real
            start_timer()
            run_controller(price_update=True) # Send the price update flag to indicate that new pricing data has been received.
            elapsed_time("Controller Run")

            logger.info(f"General: {amber_data.general_price} c/kWh  Feed In: {amber_data.feedIn_price} c/kWh  Max 12hr Feed In: {amber_data.feedIn_max_forecast_price} c/kWh")    
            logger.info(f"Seconds till next update: {round(next_amber_update_timestamp - time.time())}")
            logger.info("....")
    
    
    run_controller() # Run the selected controller  
    
    
    update_sensors(amber_data)
    

last_loop_timestamp = 0
last_alive_time_timestamp = 0
while True:
    try:
        if(time.time() - last_loop_timestamp >= 10): # Run the loop every 10 seconds to reduce CPU usage
            last_loop_timestamp = time.time()
            main_loop_code()
        
        if(time.time() - int(last_alive_time_timestamp) >= 1):
            last_alive_time_timestamp = time.time()
            ha_mqtt.alive_time_sensor.set_state(round(time.time()-app_start_timestamp))

        time.sleep(1) # Sleep a little to reduce CPU usage, we don't need to check the time constantly
        

    except KeyboardInterrupt:
        logger.error("Keyboard Interrupt, Shutting down...")
        streamlit_proc.terminate()
        break
    
    except Exception as e:
        PrintError(e)

    