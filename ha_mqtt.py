from paho.mqtt.client import Client, MQTTMessage
import paho.mqtt.client as mqtt
from ha_mqtt_discoverable import Settings, DeviceInfo
from ha_mqtt_discoverable.sensors import Select, SelectInfo, SensorInfo, Sensor, NumberInfo, Number, Switch, SwitchInfo
import time
import logging
import const
import config_manager

logger = logging.getLogger(__name__)

# Configure the required parameters for the MQTT broker
mqtt_settings = Settings.MQTT(host=const.MQTT_HOST, username=config_manager.MQTT_USER, password=config_manager.MQTT_PASS, port=const.MQTT_PORT)

DEVICE_PREFIX = "mpc_energy_manager"

def uid(name):
    return f"{DEVICE_PREFIX}_{name}"

# Define the device. At least one of `identifiers` or `connections` must be supplied
device_info = DeviceInfo(name="MPC Energy Manager Device", identifiers="mpc-energy-py")


def CreateSensor(name, unique_id, unit_of_measurement, state_class="measurement", device_class=None):
    sensor_info = SensorInfo(name=name, unique_id=uid(unique_id), device=device_info, unit_of_measurement=unit_of_measurement, state_class=state_class, device_class=device_class)
    sensor_settings = Settings(mqtt=mqtt_settings, entity=sensor_info)
    return Sensor(sensor_settings)

class CreateSelectInput():
    def __init__(self, name, unique_id, options):
        self.state = None
        self.options = options
        self.name = name
        select_info = SelectInfo(name=name, unique_id=uid(unique_id), device=device_info, options=options, device_class=None,retain=True)
        settings = Settings(mqtt=mqtt_settings, entity=select_info)
        self.entity = Select(settings, self.callback_function)
        self.entity.select_option(options[0])
        self.entity.write_config()
        
    def callback_function(self, client: Client, user_data, message: MQTTMessage):
        self.state = message.payload.decode()
        self.entity.select_option(self.state)
        
    def set_state(self, state):
        if(state in self.options):
            self.entity.select_option(state)
            self.state = state
        else:
            raise(f"{state} option is not a valid option: {self.options} for {self.name} selector")


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
    options=["RBC", "MPC"]
)


base_load_sensor = CreateSensor(
    name = "Base Load",
    unique_id="base_load_python",
    unit_of_measurement="w"
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


target_discharge_sensor = CreateSensor(
    name = "Target Discharge Price",
    unique_id="target_discharge_price_python",
    unit_of_measurement="c/kWh"
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

def initalise_entities(): # Initalise entities and get them discovered by the ha mqtt service
    automatic_control_switch.set_state(False)
    working_mode_sensor.set_state("Self Consumption")
    system_state_sensor.set_state("Self Consumption")
    amber_api_calls_remaining_sensor.set_state(0)
    kwh_required_overnight_sensor.set_state(0)
    alive_time_sensor.set_state(0)
    current_feedIn_sensor.set_state(0)
    current_general_price_sensor.set_state(0)
    max_feedIn_sensor.set_state(0)
    target_discharge_sensor.set_state(0)
    kwh_discharged_sensor.set_state(0)
    kwh_remaining_sensor.set_state(0)
    effective_price_sensor.set_state(0)
    base_load_sensor.set_state(0)
    avg_daily_load_sensor.set_state(0)
    kwh_required_till_sundown_sensor.set_state(0)
    estimated_price_status_sensor.set_state(0)
    time.sleep(10)



def check_entity_exists(state_topic, broker_host, port=1883, username=None, password=None, timeout=5):
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

    client.connect(broker_host, port, keepalive=timeout)
    client.loop_start()

    # wait for message or timeout
    start = time.time()
    while time.time() - start < timeout:
        if result["exists"]:
            break
        time.sleep(0.1)


    client.loop_stop()
    client.disconnect()

    return result["exists"]

state_topic = "homeassistant/switch/MPC-Energy-Manager-Device/Automatic-Control/config" # Check to see if the switch exists on the mqtt brocker, if not, set inital values for all entities

if not check_entity_exists(state_topic, const.MQTT_HOST, const.MQTT_PORT, config_manager.MQTT_USER, config_manager.MQTT_PASS):
    logger.warning("MQTT Topics were not found on the brocker, creating required entities.3")
    # Sensor doesn’t exist — set initial values
    initalise_entities()
