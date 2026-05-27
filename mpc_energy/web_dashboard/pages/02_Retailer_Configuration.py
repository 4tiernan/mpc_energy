import streamlit as st
import config_manager
import json
import os

st.set_page_config(page_title="Retailer Configuration", layout="wide")
st.title("⚡ Retailer Configuration")

config = config_manager.load_config()

retailer = st.selectbox("Select Energy Retailer", ["amber", "flow"], 
                        index=0 if config.get("energy_retailer") == "amber" else 1)

new_config = {"energy_retailer": retailer}

if retailer == "amber":
    st.subheader("Amber Electric Settings")
    new_config["amber_api_key"] = st.text_input("Amber API Key", value=config.get("amber_api_key", ""), type="password")
    new_config["amber_site_id"] = st.text_input("Amber Site ID (Leave blank to discover in logs)", value=config.get("amber_site_id", ""))
    
elif retailer == "flow":
    st.subheader("Flow Power Settings")
    new_config["flow_import_price_entity_id"] = st.text_input("Import Price Entity ID", value=config.get("flow_import_price_entity_id", ""))
    new_config["flow_export_price_entity_id"] = st.text_input("Export Price Entity ID", value=config.get("flow_export_price_entity_id", ""))
    new_config["flow_price_forecast_entity_id"] = st.text_input("Price Forecast Entity ID", value=config.get("flow_price_forecast_entity_id", ""))

st.divider()
st.subheader("Demand Tariff (Optional)")
new_config["demand_price"] = st.text_input("Demand Price ($/kW)", value=config.get("demand_price", ""))
col1, col2 = st.columns(2)
new_config["demand_window_start"] = col1.text_input("Window Start (HH:MM)", value=config.get("demand_window_start", "16:00"))
new_config["demand_window_end"] = col2.text_input("Window End (HH:MM)", value=config.get("demand_window_end", "21:00"))

if st.button("Save Retailer Configuration"):
    config_manager.save_local_config(new_config)
    st.success("Configuration saved! Please restart the add-on for changes to take effect.")
    
    # Setup Flow redirection
    if not config.get("solcast_forecast_today_entity_id"):
        st.info("Next step: Solar Forecast Configuration")
        if st.button("Proceed to Solar Forecast Configuration"):
            st.switch_page("pages/03_Solar_Forecast_Configuration.py")
