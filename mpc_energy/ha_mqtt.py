from paho.mqtt.client import Client, MQTTMessage
import paho.mqtt.client as mqtt
from ha_mqtt_discoverable import Settings, DeviceInfo
from ha_mqtt_discoverable.sensors import Select, SelectInfo, SensorInfo, Sensor, NumberInfo, Number, Switch, SwitchInfo
import time
import const
import config_manager
from mpc_logger import logger


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
    
    def publish_command(self, command):
        command_topic = getattr(getattr(self.entity, "_entity", None), "_command_topic", None)
        if command_topic is not None:
            self.entity._mqtt_client.publish(command_topic, payload=command, qos=0, retain=True)
        
    def set_state(self, state, publish_command=False):
        if(state in self.options):
            if publish_command:
                self.publish_command(state)
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
        "Solar To Load"
    ]
)

control_mode_override_duration_selector = CreateSelectInput(
    name="Control Mode Override Duration",
    unique_id="control_mode_override_duration",
    options=["5", "15", "30", "60", "120", "240", "360", "Till Price Change"]
)

ev_charging_mode_selector = CreateSelectInput(
    name="EV Charging Mode",
    unique_id="ev_charging_mode",
    options=[
        "Charging Disabled",
        "Solar Smart",
        "Ready by Time",
        "Force On",
    ]
)


ready_by_time_selector = CreateSelectInput(
    name="EV Ready By Time",
    unique_id="ev_ready_by_time",
    options=[
        "NA",
        "00:00", "00:30",
        "01:00", "01:30",
        "02:00", "02:30",
        "03:00", "03:30",
        "04:00", "04:30",
        "05:00", "05:30",
        "06:00", "06:30",
        "07:00", "07:30",
        "08:00", "08:30",
        "09:00", "09:30",
        "10:00", "10:30",
        "11:00", "11:30",
        "12:00", "12:30",
        "13:00", "13:30",
        "14:00", "14:30",
        "15:00", "15:30",
        "16:00", "16:30",
        "17:00", "17:30",
        "18:00", "18:30",
        "19:00", "19:30",
        "20:00", "20:30",
        "21:00", "21:30",
        "22:00", "22:30",
        "23:00", "23:30"
    ]
)

target_ev_charge_rate_sensor = CreateSensor(
    name = "Target EV Charge Rate",
    unique_id="target_ev_charge_rate",
    unit_of_measurement="kW"
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
    target_ev_charge_rate_sensor.set_state(0)
    ev_charging_mode_selector.set_state("Solar Smart")
    ready_by_time_selector.set_state("NA")

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
    logger.warning("MQTT Topics were not found on the brocker, creating required entities.")
    # Sensor doesn’t exist — set initial values
    initalise_entities()
