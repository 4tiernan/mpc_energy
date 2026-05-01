import streamlit as st

import optional_loads

st.set_page_config(page_title="Optional Loads", layout="wide")

st.title("Optional Loads Configuration")
st.caption("Add additional load sensors that should be included in total house load calculations.")

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
        col1, col2 = st.columns([2, 3])
        name = col1.text_input(
            f"Load name {idx + 1}",
            value=row.get("name", ""),
            key=f"optional_load_name_{idx}",
            placeholder="EV Charger",
        )
        entity_id = col2.text_input(
            f"Entity ID {idx + 1}",
            value=row.get("entity_id", ""),
            key=f"optional_load_entity_{idx}",
            placeholder="sensor.ev_charger_power",
        )
        edited_rows.append({"name": name, "entity_id": entity_id})

    add_row = st.form_submit_button("Add row")
    save = st.form_submit_button("Save optional loads")

if add_row:
    st.session_state.optional_load_rows = edited_rows + [{"name": "", "entity_id": ""}]
    st.rerun()

if save:
    optional_loads.save_optional_loads(edited_rows)
    st.session_state.optional_load_rows = optional_loads.load_optional_loads()
    st.success("Optional loads saved. These are stored under /data so they persist across add-on updates.")