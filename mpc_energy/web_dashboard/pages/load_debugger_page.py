import streamlit as st
import plotly.graph_objects as go
import datetime
import pandas as pd
import numpy as np
from ha_api import HomeAssistantAPI
from plants.plant_manager import GetPlant, load_plant_config
import const
import data_helpers
from loads.optional_loads import load_optional_load_instances
from mpc_logger import logger

st.set_page_config(page_title="Load Debugger", layout="wide")

st.sidebar.page_link("webserver.py", label="Dashboard", icon="📊")
st.sidebar.page_link("pages/optional_loads_page.py", label="Optional Loads", icon="⚙️")
st.sidebar.page_link("pages/plant_config_page.py", label="Plant Configuration", icon="🏭")
st.sidebar.page_link("pages/load_debugger_page.py", label="Load Debugger", icon="📈")

st.title("📈 Load Profile Debugger")
st.write("This tool visualizes the data used by `update_load_avg` to predict your household consumption.")

# 1. Initialization
ha = HomeAssistantAPI(base_url=const.HA_API_URL, token=const.HA_TOKEN)
opt_loads = load_optional_load_instances(ha, ha.local_tz, None)
plant = GetPlant(ha, opt_loads)

if not plant:
    st.error("Plant not configured. Please go to Plant Configuration first.")
    st.stop()

# 2. Controls
col_ctrl1, col_ctrl2 = st.columns(2)
days_to_fetch = col_ctrl1.slider("Days of history to analyze", 1, 14, 3)
bin_size = col_ctrl2.selectbox("Bin Size (minutes)", [5, 15, 30, 60], index=0)

if st.button("Fetch and Analyze Data"):
    with st.spinner(f"Fetching last {days_to_fetch} days of load data..."):
        # Replicate logic from BasePlant.update_load_avg
        today = datetime.datetime.now(ha.local_tz).date()
        end_date = today - datetime.timedelta(days=1)
        start_date = end_date - datetime.timedelta(days=days_to_fetch)
        
        start = datetime.datetime.combine(start_date, datetime.time.min, tzinfo=ha.local_tz)
        end = datetime.datetime.combine(end_date, datetime.time.max, tzinfo=ha.local_tz)

        # Get raw data
        load_power_history = ha.get_history(plant.load_power_entity_id, start_time=start, end_time=end)
        
        if not load_power_history:
            st.error(f"No history found for entity: {plant.load_power_entity_id}")
            st.stop()

        # Binning
        binned_load = data_helpers.bin_data(load_power_history, bin_size, start, end)
        
        # Debiasing
        total_load_data = [b.avg_state if b.avg_state is not None else 0.0 for b in binned_load]
        debiased_data = list(total_load_data)
        optional_load_data = [0.0] * len(total_load_data)

        if opt_loads:
            for load in opt_loads:
                opt_history = load.get_historical_power(start=start, end=end, bin_period=bin_size)
                if opt_history:
                    for i in range(min(len(debiased_data), len(opt_history))):
                        opt_val = opt_history[i].avg_state if opt_history[i].avg_state is not None else 0.0
                        optional_load_data[i] += opt_val
                        debiased_data[i] = max(debiased_data[i] - opt_val, 0.0)

        # Reconstruct into Days
        fig = go.Figure()
        all_days_matrix = []
        all_opt_matrix = []
        all_total_matrix = []
        
        # Calculate bins per day
        bins_per_day = int(24 * 60 / bin_size)
        
        for d in range(days_to_fetch):
            start_idx = d * bins_per_day
            end_idx = start_idx + bins_per_day
            day_slice = debiased_data[start_idx:end_idx]
            
            if len(day_slice) == bins_per_day:
                all_days_matrix.append(day_slice)
                all_opt_matrix.append(optional_load_data[start_idx:end_idx])
                all_total_matrix.append(total_load_data[start_idx:end_idx])
                # Plot individual day
                x_time = [datetime.time(hour=m // 60, minute=m % 60) for m in range(0, 1440, bin_size)]
                fig.add_trace(go.Scatter(
                    x=x_time, y=day_slice, 
                    mode='lines', 
                    name=f"Day -{days_to_fetch - d}",
                    line=dict(width=1, color='rgba(100, 100, 100, 0.3)'),
                    hoverinfo='skip'
                ))

        # Calculate Average
        if all_days_matrix:
            avg_day = np.mean(all_days_matrix, axis=0)
            avg_opt = np.mean(all_opt_matrix, axis=0)
            avg_total = np.mean(all_total_matrix, axis=0)
            x_time = [datetime.time(hour=m // 60, minute=m % 60) for m in range(0, 1440, bin_size)]
            
            fig.add_trace(go.Scatter(
                x=x_time, y=avg_total,
                mode='lines',
                name='Average Total Load',
                line=dict(color='blue', width=2, dash='dot')
            ))

            fig.add_trace(go.Scatter(
                x=x_time, y=avg_opt,
                mode='lines',
                name='Average Optional Load',
                line=dict(color='orange', width=2)
            ))

            fig.add_trace(go.Scatter(
                x=x_time, y=avg_day,
                mode='lines',
                name='Average Base Load (Debiased)',
                line=dict(color='green', width=4)
            ))

            fig.update_layout(
                title=f"Household Load Profile Analysis ({days_to_fetch} Days)",
                xaxis_title="Time of Day",
                yaxis_title="Load Power (kW)",
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )

            st.plotly_chart(fig, use_container_width=True)
            
            st.subheader("Statistical Summary")
            st.write(f"Average Daily Energy Consumption (Base Load): **{round(sum(avg_day) * (bin_size/60), 2)} kWh**")
            st.write(f"Average Daily Energy Consumption (Optional Loads): **{round(sum(avg_opt) * (bin_size/60), 2)} kWh**")
            st.write(f"Peak Base Load: **{round(max(avg_day), 2)} kW** at {x_time[np.argmax(avg_day)]}")