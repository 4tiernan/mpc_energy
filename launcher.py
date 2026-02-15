import subprocess
import sys
import json
import paho.mqtt.client as mqtt

import time
from amber_api import AmberAPI  
from ha_api import HomeAssistantAPI
import PlantControl
from api_token_secrets import HA_URL, HA_TOKEN, AMBER_API_TOKEN, SITE_ID, MQTT_HOST, MQTT_USER, MQTT_PASS
from MPC import MPC


mqtt_client = mqtt.Client()
mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS) 
mqtt_client.connect(MQTT_HOST, 1883)
mqtt_client.loop_start()



amber = AmberAPI(AMBER_API_TOKEN, SITE_ID, errors=True)

plant = PlantControl.Plant(HA_URL, HA_TOKEN, errors=True) 
ha = HomeAssistantAPI(
        base_url=HA_URL,
        token=HA_TOKEN,
        errors=True
    )

mpc = MPC(amber, plant, ha)


# Start Streamlit dashboard
streamlit_proc = subprocess.Popen([
    sys.executable,
    "-m",
    "streamlit",
    "run",
    "webserver.py",
    "--server.headless=true",
    "--theme.base",
    "light"
])

print("Streamlit dashboard started")



try:
    # Your main loop
    output = mpc.run_optimisation()
    #mpc.display_results(output)
    # ---------------- send a message ------------------
    mqtt_client.publish("home/mpc/output", json.dumps(output), retain=True)
    while True:
        time.sleep(1)

except KeyboardInterrupt:
    print("Shutting down...")
    streamlit_proc.terminate()
