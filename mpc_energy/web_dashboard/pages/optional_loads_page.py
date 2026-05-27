import streamlit as st

import loads.optional_loads as optional_loads
import loads.EV_chargers.EV_charger as ev_charger

st.set_page_config(page_title="Optional Loads", layout="wide")

st.sidebar.page_link("webserver.py", label="Dashboard", icon="📊")
st.sidebar.page_link("pages/optional_loads_page.py", label="Optional Loads", icon="⚙️")
st.sidebar.page_link("pages/plant_config_page.py", label="Plant Configuration", icon="🏭")
st.sidebar.page_link("pages/hw_debugger_page.py", label="HW Debugger", icon="🌡️")
st.sidebar.page_link("pages/load_debugger_page.py", label="Load Debugger", icon="📈")

st.title("Optional Loads Configuration")
st.caption("Add optional loads and EV-style constraints for MPC/Plant Control integration.")

if "optional_load_rows" not in st.session_state:
    st.session_state.optional_load_rows = optional_loads.load_optional_loads()

col_btn1, col_btn2 = st.columns(2)
if col_btn1.button("Reload from saved config"):
    st.session_state.optional_load_rows = optional_loads.load_optional_loads()

if col_btn2.button("Clear and delete all saved loads"):
    optional_loads.save_optional_loads([])
    st.session_state.optional_load_rows = []
    st.success("All optional loads deleted.")
    st.rerun()

rows = st.session_state.optional_load_rows
edited_rows: list[dict] = []
delete_row_idx = None

for idx, row in enumerate(rows):
    with st.container(border=True):
        col_t1, col_t2, col_t3 = st.columns([2, 2, 0.4])
        l_type = col_t1.selectbox(
            "Load Type",
            options=["ev", "hot_water"],
            index=["ev", "hot_water"].index(row.get("load_type", "ev") if row.get("load_type") != "generic" else "ev"),
            key=f"optional_load_type_{idx}",
            format_func=lambda x: "EV" if x == "ev" else x.replace("_", " ").title()
        )
        
        name = col_t2.text_input("Load Name", value=row.get("name", ""), key=f"name_input_{idx}")
        
        col_t3.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        if col_t3.button("🗑️", key=f"del_{idx}", help="Delete this load", use_container_width=True):
            delete_row_idx = idx

        # Local state for field mapping
        nominal_ac_voltage = str(row.get("nominal_ac_voltage", "230.0"))
        ev_min_charge_amps = str(row.get("min_charge_current", "5.0"))
        ev_max_charge_amps = str(row.get("max_charge_current", "32.0"))
        ev_charge_current_entity_id = row.get("charge_current_entity_id", "")
        ev_charge_enable_entity_id = row.get("charge_enable_entity_id", "")
        charger_model = row.get("charger_model", "Tesla API")
        lvl_ent = row.get("level_entity_id", "")
        cap = str(row.get("capacity_kwh", "0.0"))
        min_lim = str(row.get("min_level_limit", "0.0"))
        opt_min_lim = str(row.get("optimal_daily_min_soc", "0.0"))
        max_lim = str(row.get("max_level_limit", "100.0"))
        min_p = str(row.get("min_charge_power_kw", "0.0"))
        max_p = str(row.get("max_charge_power_kw", "0.0"))
        p_ent = row.get("power_entity_id", "")
        plug_ent = row.get("plugged_in_entity_id", "")
        three_phase_available_entity_id = row.get("three_phase_available_entity_id", "")
        three_phase_available = row.get("three_phase_available", False)
        debias_load = row.get("debias_load", True)
        reward = str(row.get("reward_cents_per_kwh", "0.0"))
        vol = str(row.get("volume_l", "0.0"))
        tmin = str(row.get("temp_min", "0.0"))
        tmax = str(row.get("temp_max", "0.0"))
        hw_power_unit_scale = row.get("hw_power_unit_scale", "kW")

        if l_type == "ev":
            c1, c2, c3 = st.columns(3)
            lvl_ent = c1.text_input("Battery SOC Entity ID (%)", value=lvl_ent, key=f"ev_soc_{idx}")
            cap = c2.text_input("Battery Capacity (kWh)", value=cap, key=f"ev_cap_{idx}")

            charger_model = c3.selectbox(
                "Charger Model",
                options=ev_charger.charger_models,
                index=ev_charger.charger_models.index(charger_model) if charger_model in ev_charger.charger_models else 0,
                key=f"ev_charger_model_{idx}"
            )
            
            c4, c5, c6 = st.columns(3)
            min_lim = c4.text_input("Min Battery SOC (%)", value=min_lim, key=f"ev_minlim_{idx}")
            opt_min_lim = c5.text_input("Optimal Daily Min SOC (%)", value=opt_min_lim, key=f"ev_optminlim_{idx}")
            max_lim = c6.text_input("Max Battery SOC (%)", value=max_lim, key=f"ev_maxlim_{idx}")
            
            reward = st.text_input("Charge Reward (c/kWh)", value=reward, key=f"ev_rew_{idx}")
            
            if charger_model == "Tesla API":
                st.write("---")
                st.caption("Tesla API Specific Configuration")
                c_t1, c_t2, c_t3 = st.columns(3)
                nominal_ac_voltage = c_t1.text_input("Nominal AC Voltage (V)", value=nominal_ac_voltage, key=f"ev_t_volt_{idx}")
                ev_min_charge_amps = c_t2.text_input("Min Charge Current (A)", value=ev_min_charge_amps, key=f"ev_t_min_a_{idx}")
                ev_max_charge_amps = c_t3.text_input("Max Charge Current (A)", value=ev_max_charge_amps, key=f"ev_t_max_a_{idx}")
                c_t4, c_t5 = st.columns(2)
                ev_charge_current_entity_id = c_t4.text_input("Charge Current Entity ID", value=ev_charge_current_entity_id, key=f"ev_t_cur_ent_{idx}")
                ev_charge_enable_entity_id = c_t5.text_input("Charge Enable Entity ID", value=ev_charge_enable_entity_id, key=f"ev_t_en_ent_{idx}")

                c_t6, c_t7 = st.columns(2)
                p_ent = c_t6.text_input("Charger Power Entity ID (kW)", value=p_ent, key=f"ev_pent_{idx}")
                plug_ent = c_t7.text_input("EV Plugged In Entity ID", value=plug_ent, key=f"ev_avail_{idx}")

                c_t8, c_t9 = st.columns(2)
                three_phase_available_entity_id = c_t8.text_input("Three Phase Available Entity ID", value=three_phase_available_entity_id, key=f"ev_t_3ph_ent_{idx}")
                debias_load = c_t9.checkbox("Debias Load (Is this load counted as part of your house power consumption?)", value=debias_load if isinstance(debias_load, bool) else str(debias_load).lower() == "true", key=f"ev_debias_{idx}")

            
            elif charger_model == "SigEnergy AC Charger":
                st.write("---")
                st.caption("SigEnergy AC Charger Specific Configuration")
                c_t1, c_t2, c_t3 = st.columns(3)
                nominal_ac_voltage = c_t1.text_input("Nominal AC Voltage (V)", value=nominal_ac_voltage, key=f"ev_t_volt_{idx}")
                ev_min_charge_amps = c_t2.text_input("Min Charge Current (A)", value=ev_min_charge_amps, key=f"ev_t_min_a_{idx}")
                ev_max_charge_amps = c_t3.text_input("Max Charge Current (A)", value=ev_max_charge_amps, key=f"ev_t_max_a_{idx}")
                c_t4, c_t5 = st.columns(2)
                ev_charge_current_entity_id = c_t4.text_input("Charge Current Entity ID", value=ev_charge_current_entity_id, key=f"ev_t_cur_ent_{idx}")
                ev_charge_enable_entity_id = c_t5.text_input("Charge Enable Entity ID", value=ev_charge_enable_entity_id, key=f"ev_t_en_ent_{idx}")
                
                c_t6, c_t7 = st.columns(2)
                p_ent = c_t6.text_input("Charger Power Entity ID (kW)", value=p_ent, key=f"ev_pent_{idx}")
                plug_ent = c_t7.text_input("EV Plugged In Entity ID", value=plug_ent, key=f"ev_avail_{idx}")


                c_t8, c_t9 = st.columns(2)
                three_phase_available = c_t8.checkbox("Three Phase Available", value=three_phase_available if isinstance(three_phase_available, bool) else str(three_phase_available).lower() == "true", key=f"ev_t_3ph_{idx}")
                debias_load = c_t9.checkbox("Debias Load (Is this load counted as part of your house power consumption?)", value=debias_load if isinstance(debias_load, bool) else str(debias_load).lower() == "true", key=f"ev_debias_{idx}")

            elif charger_model == "Generic Binary":
                st.write("---")
                st.caption("Generic Binary Charger Specific Configuration")
                c_t1, c_t2 = st.columns(2)
                nominal_ac_voltage = c_t1.text_input("Nominal AC Voltage (V)", value=nominal_ac_voltage, key=f"ev_b_volt_{idx}")
                ev_max_charge_amps = c_t2.text_input("Rated Current (A)", value=ev_max_charge_amps, key=f"ev_b_max_a_{idx}")
                
                c_t3, c_t4 = st.columns(2)
                ev_charge_enable_entity_id = c_t3.text_input("Switch Entity ID", value=ev_charge_enable_entity_id, key=f"ev_b_sw_ent_{idx}")
                p_ent = c_t4.text_input("Charger Power Entity ID (kW) [Optional]", value=p_ent, key=f"ev_pent_{idx}")

                c_t5, c_t6 = st.columns(2)
                plug_ent = c_t5.text_input("EV Plugged In Entity ID [Optional]", value=plug_ent, key=f"ev_avail_{idx}")
                debias_load = c_t6.checkbox("Debias Load (Is this load counted as part of your house power consumption?)", value=debias_load if isinstance(debias_load, bool) else str(debias_load).lower() == "true", key=f"ev_debias_{idx}")

                # For binary chargers, set both min and max power to the calculated nominal power to guide the MPC
                try:
                    calc_p = str(round((float(nominal_ac_voltage) * float(ev_max_charge_amps)) / 1000.0, 2))
                    max_p, min_p = calc_p, calc_p
                except (ValueError, TypeError):
                    pass


            else:
                st.warning(f"Charger model '{charger_model}' is not yet implemented. Please ensure that you have a compatible charger model selected.")

        elif l_type == "hot_water":
            c1, c2 = st.columns(2)
            tmin = c1.text_input("Min Tank Temp (C)", value=tmin, key=f"hw_tmin_{idx}")
            tmax = c2.text_input("Max Tank Temp (C)", value=tmax, key=f"hw_tmax_{idx}")
            
            c3, c4 = st.columns(2)
            lvl_ent = c3.text_input("Tank Temperature Entity ID (C)", value=lvl_ent, key=f"hw_lvl_{idx}")
            vol = c4.text_input("Tank Volume (L)", value=vol, key=f"hw_vol_{idx}")
            
            c5, c6, c7 = st.columns([1, 1, 0.4])
            max_p = c5.text_input("Rated Power (kW)", value=max_p, key=f"hw_hp_{idx}")
            p_ent = c6.text_input("Heater Power Entity ID", value=p_ent, key=f"hw_hpent_{idx}")
            hw_power_unit_scale = c7.selectbox("Unit", options=["kW", "W"], index=0 if hw_power_unit_scale == "kW" else 1, key=f"hw_unit_{idx}")

            reward = st.text_input("Charge Reward (c/kWh)", value=reward, key=f"hw_rew_{idx}")

        edited_rows.append({
            "name": name, 
            "power_entity_id": p_ent, 
            "load_type": l_type,
            "plugged_in_entity_id": plug_ent, 
            "level_entity_id": lvl_ent,
            "capacity_kwh": cap, 
            "max_charge_power_kw": max_p,
            "min_charge_power_kw": min_p, 
            "min_level_limit": min_lim,
            "optimal_daily_min_soc": opt_min_lim,
            "max_level_limit": max_lim, 
            "reward_cents_per_kwh": reward,
            "volume_l": vol, 
            "temp_min": tmin, 
            "temp_max": tmax,
            "charger_model": charger_model, 
            "nominal_ac_voltage": nominal_ac_voltage,
            "min_charge_current": ev_min_charge_amps,
            "max_charge_current": ev_max_charge_amps,
            "charge_current_entity_id": ev_charge_current_entity_id,
            "charge_enable_entity_id": ev_charge_enable_entity_id,
            "three_phase_available_entity_id": three_phase_available_entity_id,
            "three_phase_available": three_phase_available,
            "debias_load": debias_load,
            "hw_power_unit_scale": hw_power_unit_scale,
        })

if delete_row_idx is not None:
    edited_rows.pop(delete_row_idx)
    st.session_state.optional_load_rows = edited_rows
    st.rerun()

if not edited_rows:
    st.info("No optional loads configured. Click 'Add row' to begin.")

col_act1, col_act2 = st.columns(2)
add_row = col_act1.button("Add row", use_container_width=True)
save = col_act2.button("Save optional loads", type="primary", use_container_width=True)

if add_row:
    st.session_state.optional_load_rows = edited_rows + [{"name": "", "power_entity_id": "", "load_type": "ev"}]
    st.rerun()

if save:
    # Validation: Ensure names are unique and not empty
    names = [r["name"].strip() for r in edited_rows]
    if any(not n for n in names):
        st.error("Please ensure all optional loads have a name.")
    elif len(names) != len(set(names)):
        st.error("Duplicate names detected. Each optional load must have a unique name.")
    else:
        optional_loads.save_optional_loads(edited_rows)
        st.session_state.optional_load_rows = optional_loads.load_optional_loads()
        st.success("Optional loads saved. Please restart MPC to take effect. These are stored under /data so they persist across add-on updates.")