import streamlit as st
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import paho.mqtt.client as mqtt
from api_token_secrets import MQTT_HOST, MQTT_USER, MQTT_PASS
import datetime, time
import queue
from streamlit_autorefresh import st_autorefresh

st.set_page_config(
    page_title="MPC Dashboard",
    layout="wide"
)

st_autorefresh(interval=20000, key="mpc_refresh")  # every 5 seconds


if "mqtt_queue" not in st.session_state:
    st.session_state.mqtt_queue = queue.Queue()

mqtt_queue = st.session_state.mqtt_queue


if "data_received" not in st.session_state:
    st.session_state.data_received = False


if "mpc_output" not in st.session_state:
    st.session_state.mpc_output = {}


def on_message(client, userdata, msg):
    global mqtt_queue
    mqtt_queue.put(json.loads(msg.payload))

if "mqtt_client" not in st.session_state:
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_message = on_message
    client.connect(MQTT_HOST, 1883)
    client.loop_start()
    client.subscribe("home/mpc/output")
    st.session_state.mqtt_client = client
time.sleep(0.1)
while not mqtt_queue.empty():
    st.session_state.mpc_output = mqtt_queue.get()
    st.session_state.data_received = True

if not st.session_state.data_received:
    st_autorefresh(interval=10, key="mqtt_fast_refresh") # Refresh the page instantly if there is no MQTT data




st.markdown("""
<style>
.block-container {
    padding-top: 2rem;
}
h1 {
    margin-top: 0rem;
    margin-bottom: 0.0rem;
}
</style>
""", unsafe_allow_html=True)



if(not st.session_state.data_received): # Don't continue if no mqtt data
    st.info("Waiting for MQTT data")
else:
    # -----------------------------
    # Convert time strings to datetime objects
    # -----------------------------
    try:
        time_index = [datetime.fromisoformat(t) for t in st.session_state.mpc_output["time_index"]]
    except Exception:
        time_index = list(range(len(st.session_state.mpc_output["soc"])))
        
    import web_plot
    web_plot.plot_mpc_results(st, st.session_state.mpc_output)




# -----------------------------
# Sidebar controls (MPC params)
# -----------------------------
#with st.sidebar:
#    st.header("MPC Parameters")
#
#    horizon = st.slider("Horizon (steps)", 6, 48, 24)
#    soc_init = st.slider("Initial SOC (%)", 0.0, 100.0, 50.0)
#    soc_target = st.slider("Target SOC (%)", 0.0, 100.0, 80.0)

#    p_max = st.slider("Max charge power (kW)", 1.0, 10.0, 5.0)
#    dt = st.number_input("Timestep (hours)", value=0.5)








