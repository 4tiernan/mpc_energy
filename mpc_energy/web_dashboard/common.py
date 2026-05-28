import streamlit as st
import config_manager
import time

def render_sidebar():
    """Renders the standard navigation sidebar for all MPC Energy dashboard pages."""
    st.sidebar.page_link("webserver.py", label="Dashboard", icon="📊")
    st.sidebar.page_link("pages/01_General_Configuration.py", label="General Configuration", icon="⚙️")
    st.sidebar.page_link("pages/plant_config_page.py", label="Plant Configuration", icon="🏭")
    st.sidebar.page_link("pages/02_Retailer_Configuration.py", label="Retailer Configuration", icon="⚡")
    st.sidebar.page_link("pages/03_Solar_Forecast_Configuration.py", label="Solar Forecast", icon="☀️")
    st.sidebar.page_link("pages/optional_loads_page.py", label="Optional Loads", icon="⚙️")
    st.sidebar.page_link("pages/opt_load_debugger.py", label="Opt Load Debugger", icon="🧪")
    st.sidebar.page_link("pages/load_debugger_page.py", label="Load Debugger", icon="📈")
    
    st.sidebar.divider()
    if st.sidebar.button("🔄 Restart MPC Energy", help="Restarts the main MPC integration. Required after configuration changes.", use_container_width=True):
        config_manager.trigger_restart()
        st.sidebar.success("Restart signal sent...")
        time.sleep(1)
