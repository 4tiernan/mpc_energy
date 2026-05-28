import streamlit as st
import config_manager
from web_dashboard.common import render_sidebar

st.set_page_config(page_title="General Configuration", layout="wide", initial_sidebar_state="collapsed")
render_sidebar()

st.title("⚙️ General Configuration")
st.write("Configure core system settings, safety acknowledgements, and connectivity.")

config = config_manager.load_config()

with st.form("general_settings"):
    st.subheader("⚠️ Safety & Risk Acknowledgement")
    accepted = st.checkbox("I acknowledge and accept the risks associated with the use of this software as outlined in the documentation.", 
                           value=config.get("accepted_risks", False))
    
    st.subheader("🌐 MQTT Credentials")
    st.info("Provide the credentials for your Home Assistant MQTT broker (Mosquitto).")
    mqtt_user = st.text_input("MQTT Username", value=config.get("ha_mqtt_user", ""), help="This should be the username for your MQTT broker, if using the default mosquitto broker, check the mosquito add-on config page.")
    mqtt_pass = st.text_input("MQTT Password", value=config.get("ha_mqtt_pass", ""), type="password", help="This should be the password for your MQTT broker, if using the default mosquitto broker, check the mosquito add-on config page.")
    
    st.subheader("🔔 Notifications & Logging")
    col1, col2 = st.columns(2)
    spike_level = col1.number_input("Spike Price Warning Level (c/kWh)", value=int(config.get("spike_price_warning_level", 50)), help="Set a feed in price threshold to receive notifications when the forecasted feed in price is expected to spike.")
    log_levels = ["debug", "info", "warning"]
    log_level = col2.selectbox("System Log Level", log_levels, index=log_levels.index(config.get("log_level", "info")))
    
    notification_target = st.text_input(
        "Notification Target (Mobile App Entity ID)", 
        value=config.get("notification_target", ""),
        help="Set this to the HA entity ID of a device you want to receive notifications on for spikes in feed in price, e.g. a mobile phone (notify.mobile_app_pixel_10_pro). (Leave blank to not receive notifications)"
    )
    notif_options = ["none", "price_spike_warning", "error_warning", "both"]
    notification_option = st.selectbox("Notification Types", notif_options, index=notif_options.index(config.get("notification_target_option", "none")))

    submitted = st.form_submit_button("Save General Configuration")
    if submitted:
        new_cfg = {
            "accepted_risks": accepted,
            "ha_mqtt_user": mqtt_user,
            "ha_mqtt_pass": mqtt_pass,
            "spike_price_warning_level": spike_level,
            "notification_target": notification_target,
            "notification_target_option": notification_option,
            "log_level": log_level
        }
        config_manager.save_local_config(new_cfg)
        st.success("General configuration saved! Please restart the integration to apply changes.")
        st.session_state["general_saved"] = True

if st.session_state.get("general_saved"):
    next_step = config_manager.get_next_setup_step()
    if next_step and next_step != "pages/01_General_Configuration.py":
        if st.button(f"Proceed to {config_manager.get_page_title(next_step)}"):
            st.session_state["general_saved"] = False
            st.switch_page(next_step)
    else:
        if st.button("🔄 Restart Now", help="Restart the integration to apply changes."):
            config_manager.trigger_restart()
            st.info("Restarting...")
