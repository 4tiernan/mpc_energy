import streamlit as st

import optional_loads

st.set_page_config(page_title="Optional Loads", layout="wide")

st.title("Optional Loads Configuration")
st.caption("Add optional loads and EV-style constraints for MPC/Plant Control integration.")

if "optional_load_rows" not in st.session_state:
    st.session_state.optional_load_rows = optional_loads.load_optional_loads()

if st.button("Reload from saved config"):
    st.session_state.optional_load_rows = optional_loads.load_optional_loads()

with st.form("optional_loads_form"):
    rows = st.session_state.optional_load_rows
    if not rows:
        rows = [{"name": "", "entity_id": ""}]

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
            value=row.get("power_entity_id", row.get("entity_id", "")),
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
        soc_entity_id = col4.text_input(f"SOC Entity ID {idx + 1}", value=row.get("soc_entity_id", ""), key=f"optional_load_soc_{idx}")
        battery_capacity_kwh = col5.text_input(f"Battery Capacity (kWh) {idx + 1}", value=str(row.get("battery_capacity_kwh", "")), key=f"optional_load_cap_{idx}")
        max_charge_power_entity_id = col6.text_input(f"Max Charge Power Entity ID {idx + 1}", value=row.get("max_charge_power_entity_id", ""), key=f"optional_load_maxp_{idx}")

        col7, col8, col9, col10 = st.columns(4)
        min_charge_power_kw = col7.text_input(f"Min Charge Power (kW) {idx + 1}", value=str(row.get("min_charge_power_kw", "")), key=f"optional_load_minp_{idx}")
        min_soc = col8.text_input(f"Min SOC (%) {idx + 1}", value=str(row.get("min_soc", "")), key=f"optional_load_minsoc_{idx}")
        max_soc = col9.text_input(f"Max SOC (%) {idx + 1}", value=str(row.get("max_soc", "")), key=f"optional_load_maxsoc_{idx}")
        charge_reward = col10.text_input(f"Charge Reward (c/kWh) {idx + 1}", value=str(row.get("charge_reward_cents_per_kwh", "")), key=f"optional_load_reward_{idx}")

        edited_rows.append({
            "name": name,
            "power_entity_id": entity_id,
            "plugged_in_entity_id": plugged_in_entity_id,
            "soc_entity_id": soc_entity_id,
            "battery_capacity_kwh": battery_capacity_kwh,
            "max_charge_power_entity_id": max_charge_power_entity_id,
            "min_charge_power_kw": min_charge_power_kw,
            "min_soc": min_soc,
            "max_soc": max_soc,
            "charge_reward_cents_per_kwh": charge_reward,
        })

    add_row = st.form_submit_button("Add row")
    save = st.form_submit_button("Save optional loads")

if add_row:
    st.session_state.optional_load_rows = edited_rows + [{"name": "", "entity_id": ""}]
    st.rerun()

if save:
    optional_loads.save_optional_loads(edited_rows)
    st.session_state.optional_load_rows = optional_loads.load_optional_loads()
    st.success("Optional loads saved. These are stored under /data so they persist across add-on updates.")