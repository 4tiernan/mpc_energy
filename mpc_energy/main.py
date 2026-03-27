import subprocess
import sys
import time
import datetime
import traceback
import config_manager
import const
from exceptions import MPCEnergyError
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
    start_time = time.time()
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

streamlit_proc = None

def start_streamlit_dashboard():
    return subprocess.Popen([
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

def send_mobile_notification(title, message):
    try:
        ha.send_notification(
            title=title,
            message=message,
            target=config_manager.notification_target
        )
    except Exception as notification_error:
        logger.error(f"Failed to send mobile notification. This likely means that the notification target is incorrect. Check the notification target and try again. Error sending notification: {notification_error}")

last_error_mobile_notification_timestamp = 0
def PrintError(e):
    logger.error(f"Exception occoured: {e}")
    if(not isinstance(e, MPCEnergyError)):
        traceback.print_exc() # Prints the full traceback to the console for unexpected errors
    
    try:
        ha.create_persistent_notification(
            title="MPC Energy Error",
            message=f"An error occurred: {e}. Check the MPC Energy Log for details."
        )
        if(config_manager.notification_target_option in ["error_warning", "both"] and config_manager.notification_target != "" and time.time() - last_error_mobile_notification_timestamp > 60*60): # If the user has selected to receive error warnings and it's been more than 60 minutes since the last error notification, send a new one
            last_error_mobile_notification_timestamp = time.time()
            send_mobile_notification(title="MPC Energy Error", message=f"An error occurred: {e}. Check the MPC Energy Log for details.")
            

    except Exception as notification_error:
        logger.error(f"Failed to create Home Assistant notification for the error. This likely means that the Home Assistant API is down. Check the API and try again. Error creating notification: {notification_error}")

def FailSafe(e):
    global EC, ha_mqtt
    PrintError(e)
    try:
        if(ha_mqtt.automatic_control_switch.state == True):
            EC.self_consumption()
            logger.warning("Succsessfully put system into safe mode after detecting an error.")        
    except:
        logger.error("Failed to put system into safe mode after detecting an error.")   

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
        streamlit_proc = start_streamlit_dashboard()
        logger.info("Streamlit dashboard started")  

        started = True
    except Exception as e:
        FailSafe(e)
        

start_time = time.time()
last_amber_update_timestamp = 0
automatic_control = True # var to keep track of whether the auto control switch is on
last_real_price_timestamp = time.time() # var to keep track of when the last real price update was received to trigger safe mode if the price updates stop working

next_amber_update_timestamp = time.time() #time to run the next amber update
partial_update = False #Indicates wheather to do a full amber update or just the current prices (if only estimated prices)

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

    override_status = control_mode_override_manager.state['active']
    override_mode = control_mode_override_manager.state['mode']
    opperating_mode = override_mode if override_status else EC.working_mode
    set_sensor_if_changed(ha_mqtt.max_feedIn_sensor, round(amber_data.feedIn_max_forecast_price))
    set_sensor_if_changed(ha_mqtt.current_feedIn_sensor, round(amber_data.feedIn_price))
    set_sensor_if_changed(ha_mqtt.current_general_price_sensor, round(amber_data.general_price))
    set_sensor_if_changed(ha_mqtt.kwh_discharged_sensor, round(plant.kwh_till_full, 2))
    set_sensor_if_changed(ha_mqtt.kwh_remaining_sensor, round(plant.kwh_stored_available, 2))
    set_sensor_if_changed(ha_mqtt.target_discharge_sensor, round(rbc.target_dispatch_price))
    set_sensor_if_changed(ha_mqtt.kwh_required_overnight_sensor, round(rbc.kwh_required_remaining, 2))    
    set_sensor_if_changed(ha_mqtt.kwh_required_till_sundown_sensor, round(rbc.kwh_required_till_sundown, 2))
    set_sensor_if_changed(ha_mqtt.amber_api_calls_remaining_sensor, amber.rate_limit_remaining)
    set_sensor_if_changed(ha_mqtt.working_mode_sensor, opperating_mode)

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
    
    set_sensor_if_changed(ha_mqtt.system_state_sensor, opperating_mode + f" {round(abs(plant.grid_power),1)}{grid_status}@{price} c/kWh ${round(plant.daily_net_profit,2)} profit")
    set_sensor_if_changed(ha_mqtt.base_load_sensor, round(1000*plant.get_base_load_estimate(),2)) # converted to w from kW
    set_sensor_if_changed(ha_mqtt.effective_price_sensor, round(mpc.current_effective_price*100)) 
    set_sensor_if_changed(ha_mqtt.avg_daily_load_sensor, round(plant.avg_daily_load,2))

    curtailment_resp = plant.system_curtailing()
    set_sensor_if_changed(ha_mqtt.curtailment_status_sensor, int(curtailment_resp['curtailing']))
    set_sensor_if_changed(ha_mqtt.curtailment_reason_sensor, curtailment_resp['reason'])

last_spike_warning_timestamp = 0
def check_for_spike(amber_data):
    global last_spike_warning_timestamp
    if(time.time() - last_spike_warning_timestamp > 60*60): # If it's been more than 60 minutes since the last spike warning, check for new ones
        for i, feedIn in enumerate(amber_data.feedIn_12hr_forecast):
            rounded_price = round(feedIn.price)
            if(rounded_price >= config_manager.spike_price_warning_level): # If the feed in price forecast contains a price above the spike warning level and it's been more than 60 minutes since the last warning, send a new warning
                last_spike_warning_timestamp = time.time()
                datetime_of_spike = amber_data.feedIn_12hr_forecast[0].time + datetime.timedelta(minutes=i*5)
                spike_time_24h = datetime_of_spike.strftime("%H:%M")

                spike_message = f"Feed in price spike forecasted! Upcoming feed in price is {rounded_price} c/kWh and will occur at {spike_time_24h}."
                logger.warning(spike_message)
                ha.create_persistent_notification(
                    title="MPC Forecast Feed In Price Spike",
                    message=spike_message
                )
                if(config_manager.notification_target_option in ["price_spike_warning", "both"] and config_manager.notification_target != ""):
                    send_mobile_notification(title="MPC Forecast Feed In Price Spike", message=spike_message)
                    
                break # Only need to send one warning for the entire forecast, so break after the first one is found

def run_controller(price_update=False):
    global automatic_control, last_control_mode
    # If Auto control has been TURNED on, print a msg and reset flag
    selected_controller = ha_mqtt.energy_controller_selector.state

    if(control_mode_override_manager.run(amber_data)): # If the user selects manual control, don't allow another controller to run.
        last_control_mode = "Manual Override"
        if(price_update):
            mpc.run_optimisation(amber_data) # Run the MPC optimisation each time the price updates to keep the plot updated
        return
    
    if(last_control_mode == "Manual Override"):
        if(ha_mqtt.automatic_control_switch.state == True):
            logger.warning(f"Manual override finished. Returning control to {selected_controller}.")

            if(selected_controller == "MPC"):
                mpc.run(amber_data)
            elif(selected_controller == "RBC"):
                rbc.run(amber_data)
            else:
                EC.self_consumption()

            last_control_mode = selected_controller

        else: # If automatic control is off, turn back to safe mode
            logger.warning(f"Manual override finished. Returning control to Safe Mode.")
            EC.self_consumption()


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
    global automatic_control, next_amber_update_timestamp, partial_update, amber_data, last_control_mode, last_real_price_timestamp
    plant.update_data() # Update the plant data once for everything else to use.

    if(time.time() >= next_amber_update_timestamp):
        start_timer()
        mpc.update_forecast_horizon() # Update forecast horizon to ensure it ends at 6am the next next day, (we need the updated forecast horizon before getting the amber data to ensure we get the correct amount of forecast data based on the current time of day)
        if(partial_update):
            amber_data = amber.get_data(
                partial_update=True,
                forecast_hrs=mpc.forecast_hrs,
                sim_start=mpc.sim_start,
                sim_end=mpc.sim_end,
            )
        else:
            amber_data = amber.get_data(
                forecast_hrs=mpc.forecast_hrs,
                sim_start=mpc.sim_start,
                sim_end=mpc.sim_end,
            )
        
        elapsed_time("Amber Data")

        set_sensor_if_changed(ha_mqtt.estimated_price_status_sensor, int(amber_data.prices_estimated))

        if(amber_data.prices_estimated): # If prices are estimated, don't use them
            seconds_till_next_update = 5
            partial_update = True # Make the next update a partial one
            logger.info(f"Prices are estimated, running partial update without price update. Will update prices in {seconds_till_next_update} seconds.")

            if(time.time() - last_real_price_timestamp > 600): # If it's been more than 10 minutes since we've received a real price update, trigger safe mode
                logger.warning("Putting system in safe mode due to lack of real price updates.")
                EC.self_consumption() # Put the system into safe mode
                
        else: # If prices are real, use them
            last_real_price_timestamp = time.time() # Update the last real price timestamp to prevent false triggering of safe mode
            partial_update = False
            real_price_offset = 30 # seconds after the period begins when the real price starts
            now_datetime = datetime.datetime.now()
            seconds_till_next_update = 300 - ((now_datetime.minute * 60 + now_datetime.second) % 300) + real_price_offset

        next_amber_update_timestamp = time.time() + seconds_till_next_update #update the time here before running MPC to ensure more accurate timings
        

        if(not amber_data.prices_estimated): #If the prices are real
            run_controller(price_update=True) # Send the price update flag to indicate that new pricing data has been received.
            check_for_spike(amber_data) # Check for any spikes in the feed in price forecast and send warnings if any are found

            logger.info(f"General: {amber_data.general_price} c/kWh  Feed In: {amber_data.feedIn_price} c/kWh  Max 12hr Feed In: {amber_data.feedIn_max_forecast_price} c/kWh, {round(next_amber_update_timestamp - time.time())} seconds till next update.")    
            logger.info("....")
    
    
    run_controller() # Run the selected controller  
    
    if(ha.ha_api_went_down()): # If the API went offline, clear the sensor cache to force a publish of all MQTT sensor data
        logger.warning("Detected Home Assistant API recovery. Clearing MQTT sensor cache to republish states.")
        sensor_state_cache.clear()
        
    update_sensors(amber_data)

last_loop_timestamp = 0
last_alive_time_timestamp = 0
while True:
    try:
        regular_loop_update_due = time.time() - last_loop_timestamp >= 10
        seconds_till_price_update = next_amber_update_timestamp - time.time()

        # Run main code if a price update is due or if its been more than 10s since the last loop (but not close to the price update so we're free to run asap for the price update)
        if(time.time() >= next_amber_update_timestamp or (regular_loop_update_due and seconds_till_price_update > 20)): 
            last_loop_timestamp = time.time()
            main_loop_code()
        
        if(time.time() - int(last_alive_time_timestamp) >= 1):
            last_alive_time_timestamp = time.time()
            ha_mqtt.alive_time_sensor.set_state(round(time.time()-app_start_timestamp))

        time.sleep(0.1) # Sleep a little to reduce CPU usage, we don't need to check the time constantly
        

    except KeyboardInterrupt:
        logger.error("Keyboard Interrupt, Shutting down...")
        streamlit_proc.terminate()
        break
    
    except Exception as e:
        FailSafe(e)
    