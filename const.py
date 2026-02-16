import os

# Get the supervisor token to connect to the ha api (automatically set in HA add-ons)
HA_TOKEN = os.environ.get("SUPERVISOR_TOKEN")
if not HA_TOKEN:
    raise RuntimeError("SUPERVISOR_TOKEN not set!")


HA_API_URL = "http://supervisor/core"


# Fetch MQTT credentials automatically
MQTT_HOST = "core-mosquitto"  # internal mqtt hostname
MQTT_PORT = 1883
