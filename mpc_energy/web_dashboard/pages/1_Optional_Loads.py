import streamlit as st

import optional_loads

st.set_page_config(page_title="Optional Loads", layout="wide")

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

with st.form("optional_loads_form"):
    rows = st.session_state.optional_load_rows
    if not rows:
        rows = [{"name": "", "power_entity_id": "", "load_type": "generic"}]

    edited_rows: list[dict] = []
    for idx, row in enumerate(rows):
        with st.container(border=True):
            col_t1, col_t2 = st.columns([2, 2])
            l_type = col_t1.selectbox(
                "Load Type",
                options=["generic", "ev", "hot_water"],
                index=["generic", "ev", "hot_water"].index(row.get("load_type", "generic")),
                key=f"optional_load_type_{idx}",
                format_func=lambda x: x.replace("_", " ").title()
            )
            
            name = col_t2.text_input(
                "Load Name",
                value=row.get("name", ""),
                key=f"optional_load_name_{idx}",
                placeholder="e.g. My EV or Water Heater",
            )

            col1, col2 = st.columns(2)
            entity_id = col1.text_input(
                "Power Entity ID (kW)",
                value=row.get("power_entity_id", ""),
                key=f"optional_load_entity_{idx}",
                placeholder="sensor.load_power",
            )
            plugged_in_entity_id = col2.text_input(
                "Availability / Plugged-in Entity ID",
                value=row.get("plugged_in_entity_id", ""),
                key=f"optional_load_plugged_{idx}",
                placeholder="binary_sensor.connected",
            )

            # Conditional Fields based on type
            level_entity_id = ""
            capacity_kwh = "0.0"
            max_charge_power_entity_id = ""
            min_charge_power_kw = "0.0"
            min_limit = "0.0"
            max_limit = "100.0"
            volume_l = "0.0"
            temp_min = "0.0"
            temp_max = "0.0"

            if l_type == "ev":
                c1, c2, c3 = st.columns(3)
                level_entity_id = c1.text_input("SOC Entity ID (%)", value=row.get("level_entity_id", ""), key=f"optional_load_level_{idx}")
                capacity_kwh = c2.text_input("Battery Capacity (kWh)", value=str(row.get("capacity_kwh", "0.0")), key=f"optional_load_cap_{idx}")
                max_charge_power_entity_id = c3.text_input("Max Charge Power Entity", value=row.get("max_charge_power_entity_id", ""), key=f"optional_load_maxp_{idx}")
                
                c4, c5, c6 = st.columns(3)
                min_charge_power_kw = c4.text_input("Min Charge Power (kW)", value=str(row.get("min_charge_power_kw", "0.0")), key=f"optional_load_minp_{idx}")
                min_limit = c5.text_input("Min SOC Limit (%)", value=str(row.get("min_limit", "0.0")), key=f"optional_load_minlim_{idx}")
                max_limit = c6.text_input("Max SOC Limit (%)", value=str(row.get("max_limit", "100.0")), key=f"optional_load_maxlim_{idx}")
            
            elif l_type == "hot_water":
                c1, c2 = st.columns(2)
                level_entity_id = c1.text_input("Temperature Entity ID (°C)", value=row.get("level_entity_id", ""), key=f"optional_load_level_{idx}")
                volume_l = c2.text_input("Tank Volume (L)", value=str(row.get("volume_l", "0.0")), key=f"optional_load_vol_{idx}")
                
                c3, c4 = st.columns(2)
                temp_min = c3.text_input("Target Min Temp (°C)", value=str(row.get("temp_min", "0.0")), key=f"optional_load_tmin_{idx}")
                temp_max = c4.text_input("Target Max Temp (°C)", value=str(row.get("temp_max", "0.0")), key=f"optional_load_tmax_{idx}")

            charge_reward = st.text_input("Charge Reward (c/kWh)", value=str(row.get("charge_reward_cents_per_kwh", "0.0")), key=f"optional_load_reward_{idx}")

            edited_rows.append({
                "name": name, "power_entity_id": entity_id, "load_type": l_type,
                "plugged_in_entity_id": plugged_in_entity_id, "level_entity_id": level_entity_id,
                "capacity_kwh": capacity_kwh, "max_charge_power_entity_id": max_charge_power_entity_id,
                "min_charge_power_kw": min_charge_power_kw, "min_limit": min_limit,
                "max_limit": max_limit, "charge_reward_cents_per_kwh": charge_reward,
                "volume_l": volume_l, "temp_min": temp_min, "temp_max": temp_max,
            })

    add_row = st.form_submit_button("Add row")
    save = st.form_submit_button("Save optional loads")

if add_row:
    st.session_state.optional_load_rows = edited_rows + [{"name": "", "power_entity_id": "", "load_type": "generic"}]
    st.rerun()

if save:
    optional_loads.save_optional_loads(edited_rows)
    st.session_state.optional_load_rows = optional_loads.load_optional_loads()
    st.success("Optional loads saved. These are stored under /data so they persist across add-on updates.")