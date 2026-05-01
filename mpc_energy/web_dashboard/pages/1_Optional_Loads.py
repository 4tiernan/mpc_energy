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
        rows = [{"name": "", "power_entity_id": ""}]

    edited_rows: list[dict[str, str]] = []
    for idx, row in enumerate(rows):
        col1, col2, col3 = st.columns([2, 3, 3])
        name = col1.text_input(
            f"Load name {idx + 1}",
            value=row.get("name", ""),
            key=f"optional_load_name_{idx}",
            placeholder="EV Charger",
        )
        entity_id = col2.text_input(
            f"Power Entity ID {idx + 1}",
            value=row.get("power_entity_id", ""),
            key=f"optional_load_entity_{idx}",
            placeholder="sensor.ev_charger_power",
        )
        plugged_in_entity_id = col3.text_input(
            f"Plugged-in Entity ID {idx + 1}",
            value=row.get("plugged_in_entity_id", ""),
            key=f"optional_load_plugged_{idx}",
            placeholder="binary_sensor.ev_plugged_in",
        )

        col4, col5, col6 = st.columns(3)
        level_entity_id = col4.text_input(f"Level/SOC/Temp Entity ID {idx + 1}", value=row.get("level_entity_id", ""), key=f"optional_load_level_{idx}")
        capacity_kwh = col5.text_input(f"Capacity (kWh) {idx + 1}", value=str(row.get("capacity_kwh", "")), key=f"optional_load_cap_{idx}")
        max_charge_power_entity_id = col6.text_input(f"Max Charge Power Entity ID {idx + 1}", value=row.get("max_charge_power_entity_id", ""), key=f"optional_load_maxp_{idx}")

        col_v, col_tmin, col_tmax = st.columns(3)
        volume_l = col_v.text_input(f"Volume (L) - Hot Water Only {idx + 1}", value=str(row.get("volume_l", "")), key=f"optional_load_vol_{idx}")
        temp_min = col_tmin.text_input(f"Temp Min (°C) {idx + 1}", value=str(row.get("temp_min", "")), key=f"optional_load_tmin_{idx}")
        temp_max = col_tmax.text_input(f"Temp Max (°C) {idx + 1}", value=str(row.get("temp_max", "")), key=f"optional_load_tmax_{idx}")

        col7, col8, col9, col10 = st.columns(4)
        min_charge_power_kw = col7.text_input(f"Min Charge Power (kW) {idx + 1}", value=str(row.get("min_charge_power_kw", "")), key=f"optional_load_minp_{idx}")
        min_limit = col8.text_input(f"Min Limit (%) {idx + 1}", value=str(row.get("min_limit", "")), key=f"optional_load_minlim_{idx}")
        max_limit = col9.text_input(f"Max Limit (%) {idx + 1}", value=str(row.get("max_limit", "")), key=f"optional_load_maxlim_{idx}")
        charge_reward = col10.text_input(f"Charge Reward (c/kWh) {idx + 1}", value=str(row.get("charge_reward_cents_per_kwh", "")), key=f"optional_load_reward_{idx}")

        edited_rows.append({
            "name": name,
            "power_entity_id": entity_id,
            "plugged_in_entity_id": plugged_in_entity_id,
            "level_entity_id": level_entity_id,
            "capacity_kwh": capacity_kwh,
            "max_charge_power_entity_id": max_charge_power_entity_id,
            "min_charge_power_kw": min_charge_power_kw,
            "min_limit": min_limit,
            "max_limit": max_limit,
            "charge_reward_cents_per_kwh": charge_reward,
            "volume_l": volume_l,
            "temp_min": temp_min,
            "temp_max": temp_max,
        })

    add_row = st.form_submit_button("Add row")
    save = st.form_submit_button("Save optional loads")

if add_row:
    st.session_state.optional_load_rows = edited_rows + [{"name": "", "power_entity_id": ""}]
    st.rerun()

if save:
    optional_loads.save_optional_loads(edited_rows)
    st.session_state.optional_load_rows = optional_loads.load_optional_loads()
    st.success("Optional loads saved. These are stored under /data so they persist across add-on updates.")