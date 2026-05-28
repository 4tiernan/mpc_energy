import streamlit as st
import config_manager
from web_dashboard.common import render_sidebar

st.set_page_config(page_title="Solar Forecast Configuration", layout="wide", initial_sidebar_state="collapsed")
render_sidebar()

st.title("☀️ Solar Forecast Configuration")

config = config_manager.load_config()

st.info("Ensure the Solcast integration is installed and entities are enabled (including Day 3/4).")

new_config = {}
new_config["solcast_forecast_today_entity_id"] = st.text_input("Today's Forecast Entity", value=config.get("solcast_forecast_today_entity_id", "sensor.solcast_pv_forecast_forecast_today"))
new_config["solcast_forecast_tomorrow_entity_id"] = st.text_input("Tomorrow's Forecast Entity", value=config.get("solcast_forecast_tomorrow_entity_id", "sensor.solcast_pv_forecast_forecast_tomorrow"))
new_config["solcast_forecast_day_3_entity_id"] = st.text_input("Day 3 Forecast Entity", value=config.get("solcast_forecast_day_3_entity_id", "sensor.solcast_pv_forecast_forecast_day_3"))
new_config["solcast_forecast_day_4_entity_id"] = st.text_input("Day 4 Forecast Entity", value=config.get("solcast_forecast_day_4_entity_id", "sensor.solcast_pv_forecast_forecast_day_4"))
new_config["solcast_solar_kwh_remaining_today_entity_id"] = st.text_input("Remaining Today Entity", value=config.get("solcast_solar_kwh_remaining_today_entity_id", "sensor.solcast_pv_forecast_forecast_remaining_today"))
new_config["solcast_solar_power_this_hour_entity_id"] = st.text_input("Power This Hour Entity", value=config.get("solcast_solar_power_this_hour_entity_id", "sensor.solcast_pv_forecast_forecast_this_hour"))

if st.button("Save Solar Configuration"):
    config_manager.save_local_config(new_config)
    st.success("Configuration saved! Please restart the add-on for changes to take effect.")
    st.session_state["solar_saved"] = True

if st.session_state.get("solar_saved"):
    st.balloons()
    if st.button("🔄 Restart Now", help="Restart the integration to apply solar forecast changes."):
        config_manager.trigger_restart()
        st.info("Restarting...")

    next_step = config_manager.get_next_setup_step()
    if next_step and next_step != "pages/03_Solar_Forecast_Configuration.py":
        if st.button("Proceed to next step"):
            st.session_state["solar_saved"] = False
            st.switch_page(next_step)
