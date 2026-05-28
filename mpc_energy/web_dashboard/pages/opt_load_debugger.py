import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from loads.optional_loads import load_optional_load_instances
from ha_api import HomeAssistantAPI
import const
from web_dashboard.common import render_sidebar

st.set_page_config(page_title="Opt Load Debugger", layout="wide", initial_sidebar_state="collapsed")
render_sidebar()

st.title("🧪 Optional Load Loss Debugger")
st.caption("Analyze background degradation (Phantom Drain) for EVs or thermal losses for Hot Water.")

if "ha" not in st.session_state:
    st.session_state.ha = HomeAssistantAPI(base_url=const.HA_API_URL, token=const.HA_TOKEN)

ha = st.session_state.ha
opt_loads = load_optional_load_instances(ha, ha.local_tz, None)

if not opt_loads:
    st.info("No optional loads configured. Please add one in the 'Optional Loads' page.")
    st.stop()

selected_load_name = st.selectbox("Select Load to Diagnose", options=[l.name for l in opt_loads])
load = next(l for l in opt_loads if l.name == selected_load_name)

days_to_analyze = st.slider("Historical Days to Analyze", 1, 14, 3)

if st.button("Refresh History Data"):
    with st.spinner("Fetching and processing historical deltas..."):
        avg_delta_dict = load.get_level_delta_avg(days_ago=days_analyze, hours_update_interval=0)
else:
    avg_delta_dict = load.get_level_delta_avg(days_ago=days_to_analyze)

if not avg_delta_dict:
    st.error("No historical data found. Ensure the 'Level Entity ID' is correct and has history.")
    st.stop()

# Calculate Power equivalent of the loss
sorted_times = sorted(avg_delta_dict.keys())
deltas = [avg_delta_dict[t] for t in sorted_times]

if load.load_type == "hot_water":
    unit = "°C"
    powers = [(-d * float(getattr(load, 'volume_l', 0)) * 4.186) / 300.0 for d in deltas]
else:
    unit = "% SOC"
    powers = [(-d * float(getattr(load, 'capacity_kwh', 0)) * 0.12) for d in deltas]

df = pd.DataFrame({
    "Time": [t.strftime("%H:%M") for t in sorted_times],
    f"Delta ({unit}/5m)": deltas,
    "Estimated Loss Power (kW)": powers
})

st.subheader(f"24-Hour Average Loss Profile: {selected_load_name}")
fig = go.Figure()
fig.add_trace(go.Scatter(x=df["Time"], y=df[f"Delta ({unit}/5m)"], name=f"Delta ({unit}/5min)", line=dict(color='royalblue', width=2)))
fig.add_trace(go.Scatter(
    x=df["Time"], y=df["Estimated Loss Power (kW)"], 
    name="Estimated Loss (kW)", 
    line=dict(color='firebrick', width=2, dash='dot'),
    yaxis="y2"
))

fig.update_layout(
    xaxis_title="Time of Day",
    yaxis=dict(title=f"Change rate ({unit} per 5 min)"),
    yaxis2=dict(title="Loss Power (kW)", overlaying="y", side="right"),
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
)
st.plotly_chart(fig, use_container_width=True)

c1, c2, c3 = st.columns(3)
c1.metric("Avg Daily Loss (kWh)", round(sum(powers) * (5/60), 2))
c2.metric("Peak Loss Power (W)", round(max(powers)*1000 if powers else 0, 1))
c3.metric(f"Max 5m {unit} Drop", round(-min(deltas) if deltas else 0, 3))

with st.expander("Raw Data Table"):
    st.dataframe(df, use_container_width=True)
