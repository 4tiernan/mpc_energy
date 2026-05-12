import streamlit as st
import pandas as pd
import numpy as np
import datetime
import plotly.graph_objects as go
from loads.HW_load import HWLoad
import loads.optional_loads as optional_loads
from ha_api import HomeAssistantAPI
import config_manager

st.set_page_config(page_title="HW Load Debugger", layout="wide")

st.sidebar.page_link("webserver.py", label="Dashboard", icon="📊")
st.sidebar.page_link("pages/optional_loads_page.py", label="Optional Loads", icon="⚙️")
st.sidebar.page_link("pages/plant_config_page.py", label="Plant Configuration", icon="🏭")
st.sidebar.page_link("pages/hw_debugger_page.py", label="HW Debugger", icon="🌡️")
st.sidebar.page_link("pages/load_debugger_page.py", label="Load Debugger", icon="📈")

st.title("Hot Water Load Debugger")
st.caption("Analyze how the delta-based forecaster is interpreting your tank temperature history.")

if "ha" not in st.session_state:
    try:
        st.session_state.ha = HomeAssistantAPI() 
    except Exception as e:
        st.error(f"Failed to connect to Home Assistant API: {e}")
        st.stop()

ha = st.session_state.ha

# Load configurations and filter for HW loads
all_optional_loads = optional_loads.load_optional_loads()
hw_configs = [l for l in all_optional_loads if l.get("load_type") == "hot_water"]

if not hw_configs:
    st.info("No Hot Water loads configured. Please add one in the 'Optional Loads' page.")
    st.stop()

selected_hw_name = st.selectbox("Select HW Load to Diagnose", options=[l["name"] for l in hw_configs])
hw_config = next(l for l in hw_configs if l["name"] == selected_hw_name)

# Instantiate and configure the HWLoad object for analysis
hw_load = HWLoad.from_dict(hw_config)
hw_load.ha = ha
hw_load.local_tz = ha.local_tz

days_to_analyze = st.slider("Historical Days to Analyze", 1, 14, 3)
hw_load.load_avg_days = days_to_analyze

if st.button("Refresh History Data"):
    with st.spinner("Fetching and processing historical deltas..."):
        # Force update by setting interval to 0
        avg_delta_dict = hw_load.get_temp_delta_avg(hours_update_interval=0)
else:
    avg_delta_dict = hw_load.get_temp_delta_avg()

if not avg_delta_dict:
    st.error("No historical temperature data found for this entity. Ensure the 'Tank Temperature Entity ID' is correct and has history.")
    st.stop()

# Prepare data for visualization
sorted_times = sorted(avg_delta_dict.keys())
deltas = [avg_delta_dict[t] for t in sorted_times]
volume = float(hw_config.get("volume_l", 0))
powers = [(d * volume * 4.186) / 300.0 for d in deltas]

df = pd.DataFrame({
    "Time": [t.strftime("%H:%M") for t in sorted_times],
    "Temp Delta (°C/5m)": deltas,
    "Estimated Power (kW)": powers
})

st.subheader(f"24-Hour Average Profile: {selected_hw_name}")
fig = go.Figure()
fig.add_trace(go.Scatter(x=df["Time"], y=df["Temp Delta (°C/5m)"], name="Temp Delta (°C/5m)", line=dict(color='royalblue', width=2)))
fig.add_trace(go.Scatter(
    x=df["Time"], y=df["Estimated Power (kW)"], 
    name="Predicted Power (kW)", 
    line=dict(color='firebrick', width=2, dash='dot'),
    yaxis="y2"
))

fig.update_layout(
    xaxis_title="Time of Day",
    yaxis=dict(title="Temperature Delta (°C per 5 min)"),
    yaxis2=dict(title="Predicted Consumption (kW)", overlaying="y", side="right"),
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
)
st.plotly_chart(fig, use_container_width=True)

c1, c2, c3 = st.columns(3)
c1.metric("Average Daily Energy (kWh)", round(sum(powers) * (5/60), 2))
c2.metric("Peak Predicted Draw (kW)", round(max(powers), 2))
c3.metric("Max 5m Temp Drop (°C)", round(max(deltas), 2))

with st.expander("Raw Data Table"):
    st.dataframe(df, use_container_width=True)