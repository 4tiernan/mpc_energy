from paho.mqtt.client import Client, MQTTMessage
import paho.mqtt.client as mqtt
from ha_mqtt_discoverable import Settings, DeviceInfo
from ha_mqtt_discoverable.sensors import Select, SelectInfo, SensorInfo, Sensor, NumberInfo, Number, Switch, SwitchInfo
import time
import const
import threading
import config_manager
from mpc_logger import logger


# Configure the required parameters for the MQTT broker
mqtt_settings = Settings.MQTT(host=const.MQTT_HOST, username=config_manager.MQTT_USER, password=config_manager.MQTT_PASS, port=const.MQTT_PORT)

DEVICE_PREFIX = "mpc_energy_manager"

def uid(name):
    return f"{DEVICE_PREFIX}_{name}"

# Define the device. At least one of `identifiers` or `connections` must be supplied
device_info = DeviceInfo(name="MPC Energy Manager Device", identifiers="mpc-energy-py")

def check_entity_exists(state_topic, broker_host, port=1883, username=None, password=None, timeout=2):
    """Return True if a retained message exists for this entity, False otherwise."""
    result = {"exists": False}

    def on_connect(client, userdata, flags, rc):
        client.subscribe(state_topic)

    def on_message(client, userdata, msg):
        result["exists"] = True
        client.disconnect()  # stop after first message

    client = mqtt.Client()
    if username and password:
        client.username_pw_set(username, password)

    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(broker_host, port, keepalive=timeout)
        client.loop_start()

        # wait for message or timeout
        start = time.time()
        while time.time() - start < timeout:
            if result["exists"]:
                break
            time.sleep(0.1)
    except Exception:
        pass

    client.loop_stop()
    client.disconnect()

    return result["exists"]

ENTITIES_EXIST = check_entity_exists("homeassistant/switch/MPC-Energy-Manager-Device/Automatic-Control/config", const.MQTT_HOST, const.MQTT_PORT, config_manager.MQTT_USER, config_manager.MQTT_PASS)

def CreateSensor(name, unique_id, unit_of_measurement, state_class="measurement", device_class=None):
    sensor_info = SensorInfo(name=name, unique_id=uid(unique_id), device=device_info, unit_of_measurement=unit_of_measurement, state_class=state_class, device_class=device_class, retain=True)
    sensor_settings = Settings(mqtt=mqtt_settings, entity=sensor_info)
    return Sensor(sensor_settings)

class CreateSelectInput():
    def __init__(self, name, unique_id, options):
        self.options = options
        self.name = name
        select_info = SelectInfo(name=name, unique_id=uid(unique_id), device=device_info, options=options, device_class=None,retain=True)
        settings = Settings(mqtt=mqtt_settings, entity=select_info)
        
        # Initialize self.state with a default (first option)
        # This will be used if no retained message is found or if it's invalid
        self.state = options[0]

        # Create the Select entity, which also sets up its MQTT client and subscription
        # The command_callback will handle future commands from HA
        self.entity = Select(settings, self.callback_function)
        
        if ENTITIES_EXIST:
            # Attempt to read the retained state from the MQTT broker for this entity's state_topic
            # This needs to happen *after* self.entity is initialized, as it provides state_topic
            retained_state = self._get_retained_state_for_select(self.entity.state_topic, self.options, self.state)
            
            # Update internal state based on retained message, if found and valid
            if retained_state in self.options:
                self.state = retained_state
            else:
                # Log a warning if the retained state is invalid, but proceed with the default
                logger.warning(f"Retained state '{retained_state}' for select entity '{self.name}' is not a valid option. Defaulting to '{self.state}'.")

        # Publish the determined initial state to HA. This ensures HA's displayed state
        # matches the app's internal state, and updates any invalid retained messages.
        self.publish_state(self.state)
        self.entity.write_config()
        
    def _get_retained_state_for_select(self, state_topic, valid_options, default_value, timeout=2):
        """
        Connects a temporary MQTT client to read the retained message on a given state_topic.
        Returns the decoded payload if found and valid, otherwise the default_value.
        """
        retained_payload = {"value": default_value}
        connected_flag = threading.Event()
        message_received_flag = threading.Event()
        
        temp_client = mqtt.Client(client_id=f"temp_reader_select_{time.time_ns()}")
        if mqtt_settings.username and mqtt_settings.password:
            temp_client.username_pw_set(mqtt_settings.username, mqtt_settings.password)

        def on_message_temp(client, userdata, msg):
            retained_payload["value"] = msg.payload.decode()
            message_received_flag.set()
            client.loop_stop() # Stop the loop after receiving the message
            client.disconnect()

        def on_connect_temp(client, userdata, flags, rc, properties=None):
            if rc == 0:
                client.subscribe(state_topic)
                connected_flag.set()
            else:
                logger.error(f"Failed to connect temporary MQTT client (rc: {rc}) to read retained state for {state_topic}.")
                client.loop_stop()
                client.disconnect()

        temp_client.on_connect = on_connect_temp
        temp_client.on_message = on_message_temp

        try:
            temp_client.connect(mqtt_settings.host, mqtt_settings.port, keepalive=timeout)
            temp_client.loop_start() # Start a non-blocking loop
            
            # Wait for connection
            if not connected_flag.wait(timeout=timeout):
                logger.warning(f"Temporary MQTT client failed to connect within {timeout}s for {state_topic}.")
                return default_value # Return default if not connected
            
            # Wait for message
            if not message_received_flag.wait(timeout=timeout):
                logger.debug(f"No retained message received within {timeout}s for {state_topic}. Using default.")
            
        except Exception as e:
            logger.error(f"Error reading retained state for {state_topic}: {e}")
        finally:
            # Ensure client is stopped and disconnected
            if temp_client.is_connected():
                temp_client.disconnect()
            temp_client.loop_stop() # Ensure loop is stopped even if message not received
            
        return retained_payload["value"]

    def callback_function(self, client: Client, user_data, message: MQTTMessage):
        # This callback is for commands from HA to change the select option
        new_state = message.payload.decode()
        if new_state in self.options:
            self.set_state(new_state, publish_command=False) # Update internal state and publish to HA
        else:
            logger.warning(f"Received invalid command '{new_state}' for select entity '{self.name}'. Valid options: {self.options}. Ignoring command.")
            # Optionally, publish the current valid state back to HA to correct its display
            self.publish_state(self.state)
    
    def publish_command(self, command):
        command_topic = getattr(self.entity, "_command_topic", None)
        mqtt_client = getattr(self.entity, "mqtt_client", None)

        if command_topic is not None and mqtt_client is not None:
            mqtt_client.publish(command_topic, payload=command, qos=0, retain=True)
        else:
            logger.warning(f"Unable to publish command for {self.name}: missing MQTT command topic/client")

    def publish_state(self, state):
        state_topic = getattr(self.entity, "state_topic", None)
        mqtt_client = getattr(self.entity, "mqtt_client", None)

        if state_topic is not None and mqtt_client is not None:
            mqtt_client.publish(state_topic, payload=state, qos=0, retain=True)
        else:
            logger.warning(f"Unable to publish state for {self.name}: missing MQTT state topic/client")
            logger.warning(f"Unable to publish command for {self.name}: missing MQTT command topic/client")

        
    def set_state(self, state, publish_command=True):
        if(state in self.options):
            if publish_command:
                self.publish_command(state)
            self.publish_state(state)
            self.state = state
        else:
            raise ValueError(f"{state} option is not a valid option: {self.options} for {self.name} selector")


class CreateNumberInput():
    def __init__(self, name, unique_id, unit_of_measurement):
        self.value = None
        number_info = NumberInfo(name=name, unique_id=uid(unique_id), device=device_info, min=0, max=50, mode="box", step=1, unit_of_measurement=unit_of_measurement, retain=True)
        settings = Settings(mqtt=mqtt_settings, entity=number_info)
        # Send an MQTT message to confirm to HA that the value was changed
        self.entity = Number(settings, self.callback_function)
        
    def callback_function(self, client: Client, user_data, message: MQTTMessage):
        self.value = int(message.payload.decode())
        # Send an MQTT message to confirm to HA that the value was changed
        self.entity.set_value(self.value)


class CreateText():
    def __init__(self, name, unique_id, unit_of_measurement):
        self.value = None
        number_info = NumberInfo(name=name, unique_id=uid(unique_id), device=device_info, min=0, max=50, mode="box", step=1, unit_of_measurement=unit_of_measurement, retain=True)
        settings = Settings(mqtt=mqtt_settings, entity=number_info)
        self.entity = Number(settings, self.callback_function)
        
    def callback_function(self, client: Client, user_data, message: MQTTMessage):
        self.value = int(message.payload.decode())
        # Send an MQTT message to confirm to HA that the number was changed
        #self.entity.set_value(self.number_value)

class CreateSwitchInput():
    def __init__(self, name, unique_id):
        self.state = False
        self.name = name

        switch_info = SwitchInfo(
            name=name,
            unique_id=uid(unique_id),
            device=device_info,
            retain=True
        )

        settings = Settings(mqtt=mqtt_settings, entity=switch_info)

        self.entity = Switch(settings, self.callback_function)

        # Set initial state
        #self.entity.off()
        #self.entity.write_config()

    def callback_function(self, client: Client, user_data, message: MQTTMessage):
        payload = message.payload.decode()

        if payload == "ON":
            self.state = True
            self.entity.on()
        elif payload == "OFF":
            self.state = False
            self.entity.off()

    def set_state(self, state: bool):
        self.state = state
        if state:
            self.entity.on()
        else:
            self.entity.off()

automatic_control_switch = CreateSwitchInput(
    name="Automatic Control",
    unique_id="automatic_control_switch",
)

energy_controller_selector = CreateSelectInput(
    name="Energy Controller",
    unique_id="energy_controller",
    options=["MPC", "Safe Mode"]
)

alive_time_sensor = CreateSensor(
    name = "Alive Time",
    unique_id="alive-time-python",
    unit_of_measurement="s"
)

working_mode_sensor = CreateSensor(
    name = "Working Mode",
    unique_id="working_mode_python",
    unit_of_measurement=None,
    state_class = None
)

system_state_sensor = CreateSensor(
    name = "System State",
    unique_id="system_state_python",
    unit_of_measurement=None,
    state_class = None
)

effective_price_sensor = CreateSensor(
    name = "Effective Price",
    unique_id="effective_price_python",
    unit_of_measurement="c/kWh"
)

current_feedIn_sensor = CreateSensor(
    name = "Feed In Price",
    unique_id="current_feed_in_price_python",
    unit_of_measurement="c/kWh"
)
current_general_price_sensor = CreateSensor(
    name = "General Price",
    unique_id="current_general_price_python",
    unit_of_measurement="c/kWh"
)
amber_api_calls_remaining_sensor = CreateSensor(
    name = "Remaining API Calls",
    unique_id="remaining_api_calls_python",
    unit_of_measurement="calls"
)

max_feedIn_sensor = CreateSensor(
    name = "Max Forecasted 12hr Feed In",
    unique_id="max-forecasted-12hr-feedin-price-python",
    unit_of_measurement="c/kWh"
)


import_cost_sensor = CreateSensor(
    name = "Import Costs Today",
    unique_id="import_costs",
    unit_of_measurement="$"
)
export_profit_sensor = CreateSensor(
    name = "Export Profits Today",
    unique_id="export_profits",
    unit_of_measurement="$"
)

net_profit_sensor = CreateSensor(
    name = "Net Profits Today",
    unique_id="net_profit",
    unit_of_measurement="$"
)

profit_remaining_today_sensor = CreateSensor(
    name = "Profit Remaining Today",
    unique_id="profit_remaining_today",
    unit_of_measurement="$"
)

profit_tomorrow_sensor = CreateSensor(
    name = "Profit Tomorrow",
    unique_id="profit_tomorrow",
    unit_of_measurement="$"
)

kwh_discharged_sensor = CreateSensor(
    name = "kWh Discharged",
    unique_id="kwh_discharged_python",
    unit_of_measurement="kWh"
)

kwh_remaining_sensor = CreateSensor(
    name = "kWh Remaining",
    unique_id="kwh_remaining_python",
    unit_of_measurement="kWh"
)


kwh_required_overnight_sensor = CreateSensor(
    name = "kWh Required Overnight",
    unique_id="kwh_required_overnight_python",
    unit_of_measurement="kWh"
)

kwh_required_till_sundown_sensor = CreateSensor(
    name = "kWh Till Sundown",
    unique_id="kwh_required_till_sundown_python",
    unit_of_measurement="kWh"
)

next_grid_interaction_kwh_sensor = CreateSensor(
    name = "Next Grid Interaction",
    unique_id="next_grid_interaction_kwh_python",
    unit_of_measurement="kWh"
)

avg_daily_load_sensor = CreateSensor(
    name = "Average Daily Load",
    unique_id="avg_daily_load_python",
    unit_of_measurement="kWh"
)
estimated_price_status_sensor = CreateSensor(
    name = "Estimated Price",
    unique_id="estimated_price_python",
    unit_of_measurement=""
)

curtailment_status_sensor = CreateSensor(
    name = "Curtailment Status",
    unique_id="curtailment_status",
    unit_of_measurement=None,
    state_class = None
)

curtailment_reason_sensor = CreateSensor(
    name = "Curtailment Limit",
    unique_id="curtailment_limit",
    unit_of_measurement=None,
    state_class = None
)

control_mode_override_selector = CreateSelectInput(
    name="Control Mode Override",
    unique_id="control_mode_override",
    options=[
        "Disabled",
        "Self Consumption",
        "Exporting Excess Solar",
        "Exporting All Solar",
        "Dispatching",
        "Grid Import",
        "Partial Grid Import",
        "Solar To Load"
    ]
)

control_mode_override_duration_selector = CreateSelectInput(
    name="Control Mode Override Duration",
    unique_id="control_mode_override_duration",
    options=["5", "15", "30", "60", "120", "240", "360", "Till Price Change"]
)

def initalise_entities(): # Initalise entities and get them discovered by the ha mqtt service
    automatic_control_switch.set_state(False)
    energy_controller_selector.set_state("MPC")
    working_mode_sensor.set_state("Self Consumption")
    system_state_sensor.set_state("Self Consumption")
    amber_api_calls_remaining_sensor.set_state(0)
    kwh_required_overnight_sensor.set_state(0)
    alive_time_sensor.set_state(0)
    current_feedIn_sensor.set_state(0)
    current_general_price_sensor.set_state(0)
    max_feedIn_sensor.set_state(0)
    kwh_discharged_sensor.set_state(0)
    kwh_remaining_sensor.set_state(0)
    effective_price_sensor.set_state(0)
    next_grid_interaction_kwh_sensor.set_state(0)
    avg_daily_load_sensor.set_state(0)
    kwh_required_till_sundown_sensor.set_state(0)
    estimated_price_status_sensor.set_state(0)
    import_cost_sensor.set_state(0)
    export_profit_sensor.set_state(0)
    net_profit_sensor.set_state(0)
    profit_remaining_today_sensor.set_state(0)
    profit_tomorrow_sensor.set_state(0)
    control_mode_override_selector.set_state("Disabled")
    control_mode_override_duration_selector.set_state("15")
    curtailment_status_sensor.set_state(0)
    curtailment_reason_sensor.set_state("None")

    time.sleep(10)

if not ENTITIES_EXIST:
    logger.warning("MQTT Topics were not found on the brocker, creating required entities.")
    # Sensor doesn’t exist — set initial values
    initalise_entities()
