import streamlit as st
import config_manager
import json
import os
from web_dashboard.common import render_sidebar

st.set_page_config(page_title="Retailer Configuration", layout="wide", initial_sidebar_state="collapsed")
render_sidebar()

st.title("⚡ Retailer Configuration")

config = config_manager.load_config()

retailer = st.selectbox("Select Energy Retailer", ["amber", "flow"], 
                        index=0 if config.get("energy_retailer") == "amber" else 1)

new_config = {"energy_retailer": retailer}

if retailer == "amber":
    st.subheader("Amber Electric Settings")
    new_config["amber_api_key"] = st.text_input("Amber API Key", value=config.get("amber_api_key", ""), type="password", help="Your Amber API key. You can find this in the developer settings on the Amber Electric website (not the App).")
    new_config["amber_site_id"] = st.text_input("Amber Site ID (Leave blank to discover in logs)", value=config.get("amber_site_id", ""), help="The site ID for your Amber Electric installation. This can be found in the logs after the integration starts.")

elif retailer == "flow":
    st.subheader("Flow Power Settings")
    new_config["flow_import_price_entity_id"] = st.text_input("Import Price Entity ID", value=config.get("flow_import_price_entity_id", ""), help="The Home Assistant entity ID for your Flow Power import price (c/kWh).")
    new_config["flow_export_price_entity_id"] = st.text_input("Export Price Entity ID", value=config.get("flow_export_price_entity_id", ""), help="The Home Assistant entity ID for your Flow Power export price (c/kWh).")
    new_config["flow_price_forecast_entity_id"] = st.text_input("Price Forecast Entity ID", value=config.get("flow_price_forecast_entity_id", ""), help="The Home Assistant entity ID for your Flow Power price forecast.")

st.divider()
st.subheader("Demand Tariff (Optional)")
new_config["demand_price"] = st.text_input("Demand Price ($/kW)", value=config.get("demand_price", ""), help="This is the price per kW (not kWh) of peak demand during the demand window. (only if you have a demand tariff)")
col1, col2 = st.columns(2)
new_config["demand_window_start"] = col1.text_input("Window Start (HH:MM)", value=config.get("demand_window_start", "16:00"), help="The start time of the demand window.")
new_config["demand_window_end"] = col2.text_input("Window End (HH:MM)", value=config.get("demand_window_end", "21:00"), help="The end time of the demand window.")

if st.button("Save Retailer Configuration"):
    config_manager.save_local_config(new_config)
    st.success("Configuration saved! Please restart the add-on for changes to take effect.")
    st.session_state["retailer_saved"] = True

if st.session_state.get("retailer_saved"):
    next_step = config_manager.get_next_setup_step()
    if next_step and next_step != "pages/02_Retailer_Configuration.py":
        if st.button(f"Proceed to {config_manager.get_page_title(next_step)}"):
            st.session_state["retailer_saved"] = False
            st.switch_page(next_step)
    else:
        if st.button("🔄 Restart Now", help="Restart the integration to apply changes."):
            config_manager.trigger_restart()
            st.info("Restarting...")
