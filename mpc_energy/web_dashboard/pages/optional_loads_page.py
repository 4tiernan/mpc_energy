import streamlit as st

import loads.optional_loads as optional_loads
import loads.EV_chargers.EV_charger as ev_charger
from web_dashboard.common import render_sidebar
import config_manager

st.set_page_config(page_title="Optional Loads", layout="wide", initial_sidebar_state="collapsed")
render_sidebar()

st.title("⚙️ Optional Loads Configuration")
st.caption("Manage EV chargers and Hot Water systems for MPC optimization.")

# Wizard helper: If in the initial setup flow, allow finishing without adding loads
if config_manager.get_next_setup_step() == "pages/optional_loads_page.py":
    st.info("💡 **Not adding any optional loads?** If you don't have any devices to configure right now, click the button below to complete the setup wizard.")
    if st.button("🏁 Finish Setup & Restart Now", help="This will finalize your configuration and start the MPC."):
        optional_loads.save_optional_loads([])
        config_manager.trigger_restart()
        st.info("Restarting integration...")

if "optional_load_rows" not in st.session_state:
    st.session_state.optional_load_rows = optional_loads.load_optional_loads()

rows = st.session_state.optional_load_rows

# To prevent st.tabs from jumping back to index 0 when a name is edited, 
# we must keep the tab labels stable until a save occurs.
def refresh_tab_titles():
    st.session_state.stable_tab_titles = ["📋 Overview"] + [
        f"{'🚗' if r.get('load_type')=='ev' else '🛁'} {r.get('name', 'New Load')}" 
        for r in st.session_state.optional_load_rows
    ]

if "stable_tab_titles" not in st.session_state or len(st.session_state.stable_tab_titles) != len(rows) + 1:
    refresh_tab_titles()

tabs = st.tabs(st.session_state.stable_tab_titles)

with tabs[0]:
    st.subheader("Optional Loads Overview")
    if not rows:
        st.info("No optional loads configured. Use the 'Add' button below to get started.")
    else:
        summary_data = []
        for r in rows:
            summary_data.append({
                "Name": r.get("name"),
                "Type": r.get("load_type", "").upper(),
                "Sensor": r.get("level_entity_id", "Not Set")
            })
        st.table(summary_data)

    col_act1, col_act2 = st.columns(2)
    if col_act1.button("➕ Add New Load", use_container_width=True):
        st.session_state.optional_load_rows.append({"name": f"New Load {len(rows)+1}", "load_type": "ev", "debias_load": True})
        refresh_tab_titles()
        st.rerun()
    
    if col_act2.button("🗑️ Delete All Loads", type="secondary", use_container_width=True):
        st.session_state.optional_load_rows = []
        optional_loads.save_optional_loads([])
        refresh_tab_titles()
        st.rerun()

for idx, row in enumerate(rows):
    with tabs[idx + 1]:
        # Use a subheader inside the tab to show the updated name immediately
        st.subheader(f"Configuration: {row.get('name', 'New Load')}")
        col_t1, col_t2, col_t3 = st.columns([2, 2, 0.4])
        row["load_type"] = col_t1.selectbox(
            "Load Type",
            options=["ev", "hot_water"],
            index=["ev", "hot_water"].index(row.get("load_type", "ev") if row.get("load_type") != "generic" else "ev"),
            key=f"optional_load_type_{idx}",
            format_func=lambda x: "EV" if x == "ev" else x.replace("_", " ").title()
        )
        row["name"] = col_t2.text_input("Load Name", value=row.get("name", ""), key=f"name_input_{idx}")
        col_t3.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        if col_t3.button("🗑️", key=f"del_{idx}", help="Delete this load", use_container_width=True):
            st.session_state.optional_load_rows.pop(idx)
            refresh_tab_titles()
            st.rerun()

        if row["load_type"] == "ev":
            c1, c2, c3 = st.columns(3)
            row["level_entity_id"] = c1.text_input("Battery SOC Entity ID (%)", value=row.get("level_entity_id", ""), key=f"ev_soc_{idx}")
            row["capacity_kwh"] = c2.text_input("Battery Capacity (kWh)", value=str(row.get("capacity_kwh", "0.0")), key=f"ev_cap_{idx}")
            row["charger_model"] = c3.selectbox(
                "Charger Model",
                options=ev_charger.charger_models,
                index=ev_charger.charger_models.index(row.get("charger_model", "Tesla API")) if row.get("charger_model") in ev_charger.charger_models else 0,
                key=f"ev_charger_model_{idx}"
            )
            c4, c5, c6 = st.columns(3)
            row["min_level_limit"] = c4.text_input("Min Battery SOC (%)", value=str(row.get("min_level_limit", "0.0")), key=f"ev_minlim_{idx}")
            row["optimal_daily_min_soc"] = c5.text_input("Optimal Daily Min SOC (%)", value=str(row.get("optimal_daily_min_soc", "0.0")), key=f"ev_optminlim_{idx}")
            row["max_level_limit"] = c6.text_input("Max Battery SOC (%)", value=str(row.get("max_level_limit", "100.0")), key=f"ev_maxlim_{idx}")
            row["reward_cents_per_kwh"] = st.text_input("Charge Reward (c/kWh)", value=str(row.get("reward_cents_per_kwh", "0.0")), key=f"ev_rew_{idx}")

            if row["charger_model"] == "Tesla API":
                st.write("---")
                st.caption("Tesla API Specific Configuration")
                c_t1, c_t2, c_t3 = st.columns(3)
                row["nominal_ac_voltage"] = c_t1.text_input("Nominal AC Voltage (V)", value=str(row.get("nominal_ac_voltage", "230.0")), key=f"ev_t_volt_{idx}")
                row["min_charge_current"] = c_t2.text_input("Min Charge Current (A)", value=str(row.get("min_charge_current", "6.0")), key=f"ev_t_min_a_{idx}")
                row["max_charge_current"] = c_t3.text_input("Max Charge Current (A)", value=str(row.get("max_charge_current", "32.0")), key=f"ev_t_max_a_{idx}")
                c_t4, c_t5 = st.columns(2)
                row["charge_current_entity_id"] = c_t4.text_input("Charge Current Entity ID", value=row.get("charge_current_entity_id", ""), key=f"ev_t_cur_ent_{idx}")
                row["charge_enable_entity_id"] = c_t5.text_input("Charge Enable Entity ID", value=row.get("charge_enable_entity_id", ""), key=f"ev_t_en_ent_{idx}")
                c_t6, c_t7 = st.columns(2)
                row["power_entity_id"] = c_t6.text_input("Charger Power Entity ID (kW)", value=row.get("power_entity_id", ""), key=f"ev_pent_{idx}")
                row["plugged_in_entity_id"] = c_t7.text_input("EV Plugged In Entity ID", value=row.get("plugged_in_entity_id", ""), key=f"ev_avail_{idx}")
                c_t8, c_t9 = st.columns(2)
                row["three_phase_available_entity_id"] = c_t8.text_input("Three Phase Available Entity ID", value=row.get("three_phase_available_entity_id", ""), key=f"ev_t_3ph_ent_{idx}")
                row["debias_load"] = c_t9.checkbox("Debias Load", value=row.get("debias_load", True), key=f"ev_debias_{idx}")

            elif row["charger_model"] == "SigEnergy AC Charger":
                st.write("---")
                st.caption("SigEnergy AC Charger Specific Configuration")
                c_t1, c_t2, c_t3 = st.columns(3)
                row["nominal_ac_voltage"] = c_t1.text_input("Nominal AC Voltage (V)", value=str(row.get("nominal_ac_voltage", "230.0")), key=f"ev_t_volt_{idx}")
                row["min_charge_current"] = c_t2.text_input("Min Charge Current (A)", value=str(row.get("min_charge_current", "6.0")), key=f"ev_t_min_a_{idx}")
                row["max_charge_current"] = c_t3.text_input("Max Charge Current (A)", value=str(row.get("max_charge_current", "32.0")), key=f"ev_t_max_a_{idx}")
                c_t4, c_t5 = st.columns(2)
                row["charge_current_entity_id"] = c_t4.text_input("Charge Current Entity ID", value=row.get("charge_current_entity_id", ""), key=f"ev_t_cur_ent_{idx}")
                row["charge_enable_entity_id"] = c_t5.text_input("Charge Enable Entity ID", value=row.get("charge_enable_entity_id", ""), key=f"ev_t_en_ent_{idx}")
                c_t6, c_t7 = st.columns(2)
                row["power_entity_id"] = c_t6.text_input("Charger Power Entity ID (kW)", value=row.get("power_entity_id", ""), key=f"ev_pent_{idx}")
                row["plugged_in_entity_id"] = c_t7.text_input("EV Plugged In Entity ID", value=row.get("plugged_in_entity_id", ""), key=f"ev_avail_{idx}")
                c_t8, c_t9 = st.columns(2)
                row["three_phase_available"] = c_t8.checkbox("Three Phase Available", value=row.get("three_phase_available", False), key=f"ev_t_3ph_{idx}")
                row["debias_load"] = c_t9.checkbox("Debias Load", value=row.get("debias_load", True), key=f"ev_debias_{idx}")

            elif row["charger_model"] == "Generic Binary":
                st.write("---")
                st.caption("Generic Binary Charger Specific Configuration")
                c_t1, c_t2 = st.columns(2)
                row["nominal_ac_voltage"] = c_t1.text_input("Nominal AC Voltage (V)", value=str(row.get("nominal_ac_voltage", "230.0")), key=f"ev_b_volt_{idx}")
                row["max_charge_current"] = c_t2.text_input("Rated Current (A)", value=str(row.get("max_charge_current", "32.0")), key=f"ev_b_max_a_{idx}")
                c_t3, c_t4 = st.columns(2)
                row["charge_enable_entity_id"] = c_t3.text_input("Switch Entity ID", value=row.get("charge_enable_entity_id", ""), key=f"ev_b_sw_ent_{idx}")
                row["power_entity_id"] = c_t4.text_input("Charger Power Entity ID (kW) [Optional]", value=row.get("power_entity_id", ""), key=f"ev_pent_{idx}")
                c_t5, c_t6 = st.columns(2)
                row["plugged_in_entity_id"] = c_t5.text_input("EV Plugged In Entity ID [Optional]", value=row.get("plugged_in_entity_id", ""), key=f"ev_avail_{idx}")
                row["debias_load"] = c_t6.checkbox("Debias Load", value=row.get("debias_load", True), key=f"ev_debias_{idx}")

        elif row["load_type"] == "hot_water":
            c1, c2 = st.columns(2)
            row["temp_min"] = c1.text_input("Min Tank Temp (C)", value=str(row.get("temp_min", "0.0")), key=f"hw_tmin_{idx}")
            row["temp_max"] = c2.text_input("Max Tank Temp (C)", value=str(row.get("temp_max", "0.0")), key=f"hw_tmax_{idx}")
            c3, c4 = st.columns(2)
            row["level_entity_id"] = c3.text_input("Tank Temperature Entity ID (C)", value=row.get("level_entity_id", ""), key=f"hw_lvl_{idx}")
            row["volume_l"] = c4.text_input("Tank Volume (L)", value=str(row.get("volume_l", "0.0")), key=f"hw_vol_{idx}")
            c5, c6, c7 = st.columns([1, 1, 0.4])
            row["max_charge_power_kw"] = c5.text_input("Rated Power (kW)", value=str(row.get("max_charge_power_kw", "0.0")), key=f"hw_hp_{idx}")
            row["power_entity_id"] = c6.text_input("Heater Power Entity ID", value=row.get("power_entity_id", ""), key=f"hw_hpent_{idx}")
            row["hw_power_unit_scale"] = c7.selectbox("Unit", options=["kW", "W"], index=0 if row.get("hw_power_unit_scale") == "kW" else 1, key=f"hw_unit_{idx}")
            row["reward_cents_per_kwh"] = st.text_input("Charge Reward (c/kWh)", value=str(row.get("reward_cents_per_kwh", "0.0")), key=f"hw_rew_{idx}")

st.divider()
if st.button("💾 Save All Optional Loads", type="primary", use_container_width=True):
    # Validation: Ensure names are unique and not empty
    names = [r["name"].strip() for r in rows]
    if any(not n for n in names):
        st.error("Please ensure all optional loads have a name.")
    elif len(names) != len(set(names)):
        st.error("Duplicate names detected. Each optional load must have a unique name.")
    else:
        optional_loads.save_optional_loads(rows)
        refresh_tab_titles()
        st.success("Optional loads saved. Please restart MPC to take effect. These are stored under /data so they persist across add-on updates.")
        st.session_state["opt_loads_saved"] = True

if st.session_state.get("opt_loads_saved"):
    next_step = config_manager.get_next_setup_step()
    if not next_step:
        st.write("Setup complete! Once the add-on is restarted and values are valid, the MPC will begin optimizing your energy usage.")
        col_final1, col_final2 = st.columns(2)
        if col_final1.button("🔄 Restart Now", help="Restart the integration to apply changes."):
            config_manager.trigger_restart()
            st.info("Restarting...")
        if col_final2.button("Go to Dashboard", type="secondary"):
            st.session_state["opt_loads_saved"] = False
            st.switch_page("webserver.py")
    else:
        if st.button(f"Proceed to {config_manager.get_page_title(next_step)}"):
            st.session_state["opt_loads_saved"] = False
            st.switch_page(next_step)