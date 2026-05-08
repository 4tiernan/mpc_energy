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

brand_defaults = {
    "Sigenergy": {
        "estimated_daily_load_energy_consumption": 24.0,
        "battery_discharge_cost": 7.0,
        "pv_max_power_limit_entry": "",
        "import_max_power_limit_entry": "",
        "export_max_power_limit_entry": "",
        "battery_max_discharge_power_limit_entry": "sensor.sigen_plant_ess_rated_discharging_power",
        "battery_max_charge_power_limit_entry": "sensor.sigen_plant_ess_rated_charging_power",
        "inverter_max_power_limit_entry": "sensor.sigen_plant_max_active_power",
        "load_power_entity_id": "sensor.sigen_plant_consumed_power",
        "solar_power_entity_id": "sensor.sigen_plant_pv_power",
        "battery_power_entity_id": "sensor.sigen_plant_battery_power",
        "grid_power_entity_id": "sensor.sigen_plant_grid_active_power",
        "inverter_power_entity_id": "sensor.sigen_plant_plant_active_power",
        "battery_soc_entity_id": "sensor.sigen_plant_battery_state_of_charge",
        "backup_soc_entry": "number.sigen_plant_ess_backup_state_of_charge",
        "charge_cutoff_soc_entry": "number.sigen_plant_ess_charge_cut_off_state_of_charge",
        "battery_rated_capacity_entry": "sensor.sigen_plant_rated_energy_capacity",
        "battery_kwh_till_full_entity_id": "sensor.sigen_plant_available_max_charging_capacity",
        "battery_stored_energy_entity_id": "sensor.sigen_plant_available_max_discharging_capacity",
        "plant_daily_import_kwh_entity_id": "sensor.sigen_plant_daily_grid_import_energy",
        "plant_daily_export_kwh_entity_id": "sensor.sigen_plant_daily_grid_export_energy",
        "ha_ems_control_switch_entity_id": "switch.sigen_plant_remote_ems_controlled_by_home_assistant",
        "ems_control_mode_entity_id": "select.sigen_plant_remote_ems_control_mode",
        "pv_limiter_entity_id": "number.sigen_plant_pv_max_power_limit",
        "battery_discharge_limiter_entity_id": "number.sigen_plant_ess_max_discharging_limit",
        "battery_charge_limiter_entity_id": "number.sigen_plant_ess_max_charging_limit",
        "export_limiter_entity_id": "number.sigen_plant_grid_export_limitation",
        "import_limiter_entity_id": "number.sigen_plant_grid_import_limitation",
        "battery_power_sign_convention": "- Charge, + Discharge"
    },
    "Goodwe": {
        "estimated_daily_load_energy_consumption": 24.0,
        "battery_discharge_cost": 7.0,
        "pv_max_power_limit_entry": "",
        "import_max_power_limit_entry": "",
        "export_max_power_limit_entry": "5",
        "battery_max_discharge_power_limit_entry": "",
        "battery_max_charge_power_limit_entry": "",
        "inverter_max_power_limit_entry": "",
        "load_power_entity_id": "sensor.goodwe_house_consumption",
        "solar_power_entity_id": "sensor.goodwe_pv_power",
        "battery_power_entity_id": "sensor.goodwe_battery_power",
        "battery_soc_entity_id": "sensor.goodwe_battery_state_of_charge",
        "backup_soc_entry": "3",
        "charge_cutoff_soc_entry": "100",
        "battery_rated_capacity_entry": "",
        "ems_control_mode_entity_id": "select.goodwe_ems_mode",
        "ems_power_limit_entity_id": "number.goodwe_ems_power_limit",
        "grid_export_limit_switch_entity_id": "switch.goodwe_grid_export_limit_switch",
        "export_limiter_entity_id": "number.goodwe_grid_export_limit",
        "battery_power_sign_convention": "- Charge, + Discharge"
    },
    "Other": {
        "estimated_daily_load_energy_consumption": 24.0,
        "battery_discharge_cost": 7.0,
        "pv_max_power_limit_entry": "",
        "import_max_power_limit_entry": "",
        "export_max_power_limit_entry": "",
        "battery_max_discharge_power_limit_entry": "",
        "battery_max_charge_power_limit_entry": "",
        "inverter_max_power_limit_entry": "",
        "battery_power_sign_convention": "- Charge, + Discharge"
    }
}

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

    st.subheader("Brand Selection")
    brands = ["Sigenergy", "Goodwe", "Other"]
    current_brand = current_config.get("plant_brand", "Sigenergy")
    plant_brand = st.selectbox("Plant Brand", options=brands, index=brands.index(current_brand) if current_brand in brands else 0)

    def get_val(key, default_val=""):
        # Use selected brand's defaults if the brand was just changed in the UI, 
        # otherwise use what's saved in the config.
        brand_config_defaults = brand_defaults.get(plant_brand, {})
        if current_config.get("plant_brand") == plant_brand:
            return current_config.get(key, brand_config_defaults.get(key, default_val))
        return brand_config_defaults.get(key, default_val)

    with st.form("plant_settings"):
        st.subheader("General Settings")
        col_gen1, col_gen2 = st.columns(2)
        with col_gen1:
            daily_load = st.number_input("Estimated Daily Load (kWh) - Only used as a backup if load prediction fails.", value=float(get_val("estimated_daily_load_energy_consumption", 24.0)))
        with col_gen2:
            discharge_cost = st.number_input("Battery Discharge Cost (c/kWh)", value=float(get_val("battery_discharge_cost", 7.0)))

        st.subheader("Physical Power Limits (Entities or Values)")
        col1, col2 = st.columns(2)
        with col1:
            pv_limit = st.text_input("PV Max Power Limit Entity/kW", value=get_val("pv_max_power_limit_entry"))
            import_limit = st.text_input("Import Max Power Limit Entity/kW", value=get_val("import_max_power_limit_entry"))
            export_limit = st.text_input("Export Max Power Limit Entity/kW", value=get_val("export_max_power_limit_entry"))
        with col2:
            bat_dis_max = st.text_input("Battery Max Discharge Entity/kW", value=get_val("battery_max_discharge_power_limit_entry"))
            bat_chg_max = st.text_input("Battery Max Charge Entity/kW", value=get_val("battery_max_charge_power_limit_entry"))
            inv_limit_max = st.text_input("Inverter Max Power Entity/kW", value=get_val("inverter_max_power_limit_entry"))

        st.subheader("Hardware Sensors (Power)")
        col3, col4 = st.columns(2)
        with col3:
            load_p = st.text_input("Load Power Entity", value=get_val("load_power_entity_id"))
            solar_p = st.text_input("Solar Power Entity", value=get_val("solar_power_entity_id"))
            bat_p = st.text_input("Battery Power Entity", value=get_val("battery_power_entity_id"))
        with col4:
            grid_p = inv_p = ""
            if plant_brand == "Sigenergy":
                grid_p = st.text_input("Grid Power Entity", value=get_val("grid_power_entity_id"))
                inv_p = st.text_input("Inverter Power Entity", value=get_val("inverter_power_entity_id"))
            sign_options = ["- Charge, + Discharge", "+ Charge, - Discharge"]
            current_sign = get_val("battery_power_sign_convention", "- Charge, + Discharge")
            sign = st.selectbox("Battery Power Sign Convention", options=sign_options, index=sign_options.index(current_sign) if current_sign in sign_options else 0)

        st.subheader("Hardware Sensors (Energy & SOC)")
        col5, col6 = st.columns(2)
        with col5:
            bat_soc = st.text_input("Battery SOC Entity (%)", value=get_val("battery_soc_entity_id"))
            backup_soc = st.text_input("Backup SOC Entity (%)", value=get_val("backup_soc_entry"))
            cutoff_soc = st.text_input("Charge Cutoff SOC Entity (%)", value=get_val("charge_cutoff_soc_entry"))
            bat_cap = st.text_input("Battery Rated Capacity Entity", value=get_val("battery_rated_capacity_entry"))
        with col6:
            bat_till_full = bat_stored = daily_import = daily_export = ""
            if plant_brand == "Sigenergy":
                bat_till_full = st.text_input("Battery kWh Till Full Entity", value=get_val("battery_kwh_till_full_entity_id"))
                bat_stored = st.text_input("Battery Stored Energy Entity", value=get_val("battery_stored_energy_entity_id"))
            daily_import = st.text_input("Daily Import kWh Entity", value=get_val("plant_daily_import_kwh_entity_id"))
            daily_export = st.text_input("Daily Export kWh Entity", value=get_val("plant_daily_export_kwh_entity_id"))

        ems_switch = ems_mode = pv_limit_id = dis_limiter = chg_limiter = exp_limiter = imp_limiter = ""
        grid_export_switch = ems_power_limit = ""

        if plant_brand == "Sigenergy":
            st.subheader("Sigenergy Control Entities & Limiters")
            col7, col8 = st.columns(2)
            with col7:
                ems_switch = st.text_input("EMS Control Switch", value=get_val("ha_ems_control_switch_entity_id"))
                ems_mode = st.text_input("EMS Control Mode Select", value=get_val("ems_control_mode_entity_id"))
                pv_limit_id = st.text_input("PV Limiter Entity", value=get_val("pv_limiter_entity_id"))
            with col8:
                dis_limiter = st.text_input("Battery Discharge Limiter", value=get_val("battery_discharge_limiter_entity_id"))
                chg_limiter = st.text_input("Battery Charge Limiter", value=get_val("battery_charge_limiter_entity_id"))
                exp_limiter = st.text_input("Export Limiter Entity", value=get_val("export_limiter_entity_id"))
                imp_limiter = st.text_input("Import Limiter Entity", value=get_val("import_limiter_entity_id"))
        elif plant_brand == "Goodwe":
            st.subheader("GoodWe Control Entities & Limiters")
            col7, col8 = st.columns(2)
            with col7:
                ems_mode = st.text_input("EMS Control Mode Select", value=get_val("ems_control_mode_entity_id"))
                ems_power_limit = st.text_input("EMS Power Limit Entity", value=get_val("ems_power_limit_entity_id"))
            with col8:
                grid_export_switch = st.text_input("Grid Export Limit Switch", value=get_val("grid_export_limit_switch_entity_id"))
                exp_limiter = st.text_input("Grid Export Limit Entity", value=get_val("export_limiter_entity_id"))

        submitted = st.form_submit_button("Save Configuration")
        if submitted:
            new_config = {
                "plant_brand": plant_brand,
                "estimated_daily_load_energy_consumption": daily_load,
                "battery_discharge_cost": discharge_cost,
                "pv_max_power_limit_entry": pv_limit,
                "import_max_power_limit_entry": import_limit,
                "export_max_power_limit_entry": export_limit,
                "battery_max_discharge_power_limit_entry": bat_dis_max,
                "battery_max_charge_power_limit_entry": bat_chg_max,
                "inverter_max_power_limit_entry": inv_limit_max,
                "load_power_entity_id": load_p,
                "solar_power_entity_id": solar_p,
                "battery_power_entity_id": bat_p,
                "inverter_power_entity_id": inv_p if plant_brand == "Sigenergy" else "",
                "grid_power_entity_id": grid_p if plant_brand == "Sigenergy" else "",
                "battery_soc_entity_id": bat_soc,
                "backup_soc_entry": backup_soc,
                "charge_cutoff_soc_entry": cutoff_soc,
                "battery_kwh_till_full_entity_id": bat_till_full if plant_brand == "Sigenergy" else "",
                "battery_stored_energy_entity_id": bat_stored if plant_brand == "Sigenergy" else "",
                "battery_rated_capacity_entry": bat_cap,
                "battery_power_sign_convention": sign,
                "ha_ems_control_switch_entity_id": ems_switch if plant_brand == "Sigenergy" else "",
                "ems_control_mode_entity_id": ems_mode,
                "battery_discharge_limiter_entity_id": dis_limiter if plant_brand == "Sigenergy" else "",
                "battery_charge_limiter_entity_id": chg_limiter if plant_brand == "Sigenergy" else "",
                "pv_limiter_entity_id": pv_limit_id if plant_brand == "Sigenergy" else "",
                "export_limiter_entity_id": exp_limiter,
                "import_limiter_entity_id": imp_limiter if plant_brand == "Sigenergy" else "",
                "grid_export_limit_switch_entity_id": grid_export_switch if plant_brand == "Goodwe" else "",
                "ems_power_limit_entity_id": ems_power_limit if plant_brand == "Goodwe" else "",
                "plant_daily_import_kwh_entity_id": daily_import if plant_brand == "Sigenergy" else "",
                "plant_daily_export_kwh_entity_id": daily_export if plant_brand == "Sigenergy" else "",
            }
            save_config(new_config)

if __name__ == "__main__":
    plant_config_page()