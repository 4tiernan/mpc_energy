import streamlit as st
import config_manager
from web_dashboard.common import render_sidebar

st.set_page_config(page_title="General Configuration", layout="wide")
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
    mqtt_user = st.text_input("MQTT Username", value=config.get("ha_mqtt_user", ""))
    mqtt_pass = st.text_input("MQTT Password", value=config.get("ha_mqtt_pass", ""), type="password")
    
    st.subheader("🔔 Notifications & Logging")
    col1, col2 = st.columns(2)
    spike_level = col1.number_input("Spike Price Warning Level (c/kWh)", value=int(config.get("spike_price_warning_level", 25)))
    log_levels = ["debug", "info", "warning"]
    log_level = col2.selectbox("System Log Level", log_levels, index=log_levels.index(config.get("log_level", "info")))
    
    notification_target = st.text_input("Notification Target (Mobile App Entity ID)", value=config.get("notification_target", ""))
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
    from plants.plant_manager import load_plant_config
    if not load_plant_config().get("plant_brand"):
        st.info("Next step: Plant Configuration")
        if st.button("Proceed to Plant Configuration"):
            st.session_state["general_saved"] = False
            st.switch_page("pages/plant_config_page.py")
