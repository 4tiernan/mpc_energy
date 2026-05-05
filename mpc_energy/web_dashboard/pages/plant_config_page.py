import streamlit as st
import json
import os

CONFIG_PATH = "/data/plant_config.json"

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_config(config):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=4)
    st.success("Plant configuration saved! Please restart the Add-on for changes to take full effect.")

def plant_config_page():
    st.sidebar.page_link("webserver.py", label="Dashboard", icon="📊")
    st.sidebar.page_link("pages/optional_loads_page.py", label="Optional Loads", icon="⚙️")
    st.sidebar.page_link("pages/plant_config_page.py", label="Plant Configuration", icon="🏭")
    st.sidebar.page_link("pages/load_debugger_page.py", label="Load Debugger", icon="📈")

    st.title("🏭 Plant Configuration")
    st.write("Configure your hardware brand, entities, and physical plant constraints.")

    if st.button("Reset Configuration to Defaults", help="Deletes the saved configuration file and reloads default values."):
        if os.path.exists(CONFIG_PATH):
            os.remove(CONFIG_PATH)
        st.rerun()

    current_config = load_config()

    with st.form("plant_settings"):
        st.subheader("Brand Selection")
        brands = ["Sigenergy", "Goodwe", "Other"]
        current_brand = current_config.get("plant_brand", "Sigenergy")
        plant_brand = st.selectbox("Plant Brand", options=brands, index=brands.index(current_brand) if current_brand in brands else 0)

        st.subheader("General Settings")
        col_gen1, col_gen2 = st.columns(2)
        with col_gen1:
            daily_load = st.number_input("Estimated Daily Load (kWh) - Only used as a backup if load prediction fails.", value=float(current_config.get("estimated_daily_load_energy_consumption", 24.0)))
        with col_gen2:
            discharge_cost = st.number_input("Battery Discharge Cost (c/kWh)", value=float(current_config.get("battery_discharge_cost", 7.0)))

        st.subheader("Physical Power Limits (Entities or Values)")
        col1, col2 = st.columns(2)
        with col1:
            pv_limit = st.text_input("PV Max Power Limit Entity/kW", value=current_config.get("pv_max_power_limit_entity_id", ""))
            import_limit = st.text_input("Import Max Power Limit Entity/kW", value=current_config.get("import_max_power_limit_entity_id", ""))
            export_limit = st.text_input("Export Max Power Limit Entity/kW", value=current_config.get("export_max_power_limit_entity_id", ""))
        with col2:
            bat_dis_max = st.text_input("Battery Max Discharge Entity/kW", value=current_config.get("battery_max_discharge_power_limit_entity_id", "sensor.sigen_plant_ess_rated_discharging_power"))
            bat_chg_max = st.text_input("Battery Max Charge Entity/kW", value=current_config.get("battery_max_charge_power_limit_entity_id", "sensor.sigen_plant_ess_rated_charging_power"))
            inv_limit_max = st.text_input("Inverter Max Power Entity/kW", value=current_config.get("inverter_max_power_limit_entity_id", "sensor.sigen_plant_max_active_power"))

        st.subheader("Hardware Sensors (Power)")
        col3, col4 = st.columns(2)
        with col3:
            load_p = st.text_input("Load Power Entity", value=current_config.get("load_power_entity_id", "sensor.sigen_plant_consumed_power"))
            solar_p = st.text_input("Solar Power Entity", value=current_config.get("solar_power_entity_id", "sensor.sigen_plant_pv_power"))
            bat_p = st.text_input("Battery Power Entity", value=current_config.get("battery_power_entity_id", "sensor.sigen_plant_battery_power"))
        with col4:
            grid_p = st.text_input("Grid Power Entity", value=current_config.get("grid_power_entity_id", "sensor.sigen_plant_grid_active_power"))
            inv_p = st.text_input("Inverter Power Entity", value=current_config.get("inverter_power_entity_id", "sensor.sigen_plant_plant_active_power"))
            sign = st.selectbox("Battery Power Sign Convention", options=["- Charge, + Discharge", "+ Charge, - Discharge"], index=0 if current_config.get("battery_power_sign_convention", "- Charge, + Discharge") == "- Charge, + Discharge" else 1)

        st.subheader("Hardware Sensors (Energy & SOC)")
        col5, col6 = st.columns(2)
        with col5:
            bat_soc = st.text_input("Battery SOC Entity (%)", value=current_config.get("battery_soc_entity_id", "sensor.sigen_plant_battery_state_of_charge"))
            backup_soc = st.text_input("Backup SOC Entity (%)", value=current_config.get("backup_soc_entity_id", "number.sigen_plant_ess_backup_state_of_charge"))
            cutoff_soc = st.text_input("Charge Cutoff SOC Entity (%)", value=current_config.get("charge_cutoff_soc_entity_id", "number.sigen_plant_ess_charge_cut_off_state_of_charge"))
            bat_cap = st.text_input("Battery Rated Capacity Entity", value=current_config.get("battery_rated_capacity_entity_id", "sensor.sigen_plant_rated_energy_capacity"))
        with col6:
            bat_till_full = st.text_input("Battery kWh Till Full Entity", value=current_config.get("battery_kwh_till_full_entity_id", "sensor.sigen_plant_available_max_charging_capacity"))
            bat_stored = st.text_input("Battery Stored Energy Entity", value=current_config.get("battery_stored_energy_entity_id", "sensor.sigen_plant_available_max_discharging_capacity"))
            daily_import = st.text_input("Daily Import kWh Entity", value=current_config.get("plant_daily_import_kwh_entity_id", "sensor.sigen_plant_daily_grid_import_energy"))
            daily_export = st.text_input("Daily Export kWh Entity", value=current_config.get("plant_daily_export_kwh_entity_id", "sensor.sigen_plant_daily_grid_export_energy"))

        st.subheader("Control Entities & Limiters")
        col7, col8 = st.columns(2)
        with col7:
            ems_switch = st.text_input("EMS Control Switch", value=current_config.get("ha_ems_control_switch_entity_id", "switch.sigen_plant_remote_ems_controlled_by_home_assistant"))
            ems_mode = st.text_input("EMS Control Mode Select", value=current_config.get("ems_control_mode_entity_id", "select.sigen_plant_remote_ems_control_mode"))
            pv_limit_id = st.text_input("PV Limiter Entity", value=current_config.get("pv_limiter_entity_id", "number.sigen_plant_pv_max_power_limit"))
        with col8:
            dis_limiter = st.text_input("Battery Discharge Limiter", value=current_config.get("battery_discharge_limiter_entity_id", "number.sigen_plant_ess_max_discharging_limit"))
            chg_limiter = st.text_input("Battery Charge Limiter", value=current_config.get("battery_charge_limiter_entity_id", "number.sigen_plant_ess_max_charging_limit"))
            exp_limiter = st.text_input("Export Limiter Entity", value=current_config.get("export_limiter_entity_id", "number.sigen_plant_grid_export_limitation"))
            imp_limiter = st.text_input("Import Limiter Entity", value=current_config.get("import_limiter_entity_id", "number.sigen_plant_grid_import_limitation"))

        submitted = st.form_submit_button("Save Configuration")
        if submitted:
            new_config = {
                "plant_brand": plant_brand,
                "estimated_daily_load_energy_consumption": daily_load,
                "battery_discharge_cost": discharge_cost,
                "pv_max_power_limit_entity_id": pv_limit,
                "import_max_power_limit_entity_id": import_limit,
                "export_max_power_limit_entity_id": export_limit,
                "battery_max_discharge_power_limit_entity_id": bat_dis_max,
                "battery_max_charge_power_limit_entity_id": bat_chg_max,
                "inverter_max_power_limit_entity_id": inv_limit_max,
                "load_power_entity_id": load_p,
                "solar_power_entity_id": solar_p,
                "battery_power_entity_id": bat_p,
                "inverter_power_entity_id": inv_p,
                "grid_power_entity_id": grid_p,
                "battery_soc_entity_id": bat_soc,
                "backup_soc_entity_id": backup_soc,
                "charge_cutoff_soc_entity_id": cutoff_soc,
                "battery_kwh_till_full_entity_id": bat_till_full,
                "battery_stored_energy_entity_id": bat_stored,
                "battery_rated_capacity_entity_id": bat_cap,
                "battery_power_sign_convention": sign,
                "ha_ems_control_switch_entity_id": ems_switch,
                "ems_control_mode_entity_id": ems_mode,
                "battery_discharge_limiter_entity_id": dis_limiter,
                "battery_charge_limiter_entity_id": chg_limiter,
                "pv_limiter_entity_id": pv_limit_id,
                "export_limiter_entity_id": exp_limiter,
                "import_limiter_entity_id": imp_limiter,
                "plant_daily_import_kwh_entity_id": daily_import,
                "plant_daily_export_kwh_entity_id": daily_export,
            }
            save_config(new_config)

if __name__ == "__main__":
    plant_config_page()