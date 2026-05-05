import streamlit as st

import loads.optional_loads as optional_loads
import loads.EV_chargers.EV_charger as ev_charger

st.set_page_config(page_title="Optional Loads", layout="wide")

st.sidebar.page_link("webserver.py", label="Dashboard", icon="📊")
st.sidebar.page_link("pages/optional_loads_page.py", label="Optional Loads", icon="⚙️")
st.sidebar.page_link("pages/plant_config_page.py", label="Plant Configuration", icon="🏭")
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

for idx, row in enumerate(rows):
    with st.container(border=True):
        col_t1, col_t2 = st.columns([2, 2])
        l_type = col_t1.selectbox(
            "Load Type",
            options=["ev", "hot_water"],
            index=["ev", "hot_water"].index(row.get("load_type", "ev") if row.get("load_type") != "generic" else "ev"),
            key=f"optional_load_type_{idx}",
            format_func=lambda x: "EV" if x == "ev" else x.replace("_", " ").title()
        )
        
        name = col_t2.text_input("Load Name", value=row.get("name", ""), key=f"name_input_{idx}")

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
        max_lim = str(row.get("max_level_limit", "100.0"))
        min_p = str(row.get("min_charge_power_kw", "0.0"))
        max_p = str(row.get("max_charge_power_kw", "0.0"))
        p_ent = row.get("power_entity_id", "")
        plug_ent = row.get("plugged_in_entity_id", "")
        reward = str(row.get("reward_cents_per_kwh", "0.0"))
        vol = str(row.get("volume_l", "0.0"))
        tmin = str(row.get("temp_min", "0.0"))
        tmax = str(row.get("temp_max", "0.0"))

        if l_type == "ev":
            charger_model = st.selectbox(
                "Charger Model",
                options=ev_charger.charger_models,
                index=ev_charger.charger_models.index(charger_model) if charger_model in ev_charger.charger_models else 0,
                key=f"ev_charger_model_{idx}"
            )
            
            c1, c2 = st.columns(2)
            lvl_ent = c1.text_input("Battery SOC Entity ID (%)", value=lvl_ent, key=f"ev_soc_{idx}")
            cap = c2.text_input("Battery Capacity (kWh)", value=cap, key=f"ev_cap_{idx}")
            
            c3, c4 = st.columns(2)
            min_lim = c3.text_input("Min Battery SOC (%)", value=min_lim, key=f"ev_minlim_{idx}")
            max_lim = c4.text_input("Max Battery SOC (%)", value=max_lim, key=f"ev_maxlim_{idx}")
            
            c7, c8 = st.columns(2)
            p_ent = c7.text_input("Charger Power Entity ID (kW)", value=p_ent, key=f"ev_pent_{idx}")
            reward = c8.text_input("Charge Reward (c/kWh)", value=reward, key=f"ev_rew_{idx}")
            
            plug_ent = st.text_input("EV Plugged In Entity ID", value=plug_ent, key=f"ev_avail_{idx}")

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

        elif l_type == "hot_water":
            c1, c2 = st.columns(2)
            tmin = c1.text_input("Min Tank Temp (C)", value=tmin, key=f"hw_tmin_{idx}")
            tmax = c2.text_input("Max Tank Temp (C)", value=tmax, key=f"hw_tmax_{idx}")
            
            c3, c4 = st.columns(2)
            lvl_ent = c3.text_input("Tank Temperature Entity ID (C)", value=lvl_ent, key=f"hw_lvl_{idx}")
            vol = c4.text_input("Tank Volume (L)", value=vol, key=f"hw_vol_{idx}")
            
            c5, c6 = st.columns(2)
            max_p = c5.text_input("Rated Power (kW)", value=max_p, key=f"hw_hp_{idx}")
            p_ent = c6.text_input("Heater Power Entity ID", value=p_ent, key=f"hw_hpent_{idx}")

            reward = st.text_input("Charge Reward (c/kWh)", value=reward, key=f"hw_rew_{idx}")

        edited_rows.append({
            "name": name, "power_entity_id": p_ent, "load_type": l_type,
            "plugged_in_entity_id": plug_ent, "level_entity_id": lvl_ent,
            "capacity_kwh": cap, "max_charge_power_kw": max_p,
            "min_charge_power_kw": min_p, "min_level_limit": min_lim,
            "max_level_limit": max_lim, "reward_cents_per_kwh": reward,
            "volume_l": vol, "temp_min": tmin, "temp_max": tmax,
            "charger_model": charger_model, 
            "nominal_ac_voltage": nominal_ac_voltage,
            "min_charge_current": ev_min_charge_amps,
            "max_charge_current": ev_max_charge_amps,
            "charge_current_entity_id": ev_charge_current_entity_id,
            "charge_enable_entity_id": ev_charge_enable_entity_id,
        })

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
        st.success("Optional loads saved. These are stored under /data so they persist across add-on updates.")