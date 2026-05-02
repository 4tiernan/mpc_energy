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

rows = st.session_state.optional_load_rows
if not rows:
    rows = [{"name": "", "power_entity_id": "", "load_type": "ev"}]

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
        lvl_ent = row.get("level_entity_id", "")
        cap = str(row.get("capacity_kwh", "0.0"))
        min_lim = str(row.get("min_limit", "0.0"))
        max_lim = str(row.get("max_limit", "100.0"))
        min_p = str(row.get("min_charge_power_kw", "0.0"))
        max_p = row.get("max_charge_power_entity_id", "")
        p_ent = row.get("power_entity_id", "")
        plug_ent = row.get("plugged_in_entity_id", "")
        reward = str(row.get("charge_reward_cents_per_kwh", "0.0"))
        vol = str(row.get("volume_l", "0.0"))
        tmin = str(row.get("temp_min", "0.0"))
        tmax = str(row.get("temp_max", "0.0"))

        if l_type == "ev":
            c1, c2 = st.columns(2)
            lvl_ent = c1.text_input("Battery SOC Entity ID (%)", value=lvl_ent, key=f"ev_soc_{idx}")
            cap = c2.text_input("Battery Capacity (kWh)", value=cap, key=f"ev_cap_{idx}")
            
            c3, c4 = st.columns(2)
            min_lim = c3.text_input("Min Battery SOC (%)", value=min_lim, key=f"ev_minlim_{idx}")
            max_lim = c4.text_input("Max Battery SOC (%)", value=max_lim, key=f"ev_maxlim_{idx}")
            
            c5, c6 = st.columns(2)
            min_p = c5.text_input("Charger Min Power (kW)", value=min_p, key=f"ev_minp_{idx}")
            max_p = c6.text_input("Charger Max Power (kW)", value=max_p, key=f"ev_maxp_{idx}")
            
            c7, c8 = st.columns(2)
            p_ent = c7.text_input("Charger Power Entity ID (kW)", value=p_ent, key=f"ev_pent_{idx}")
            reward = c8.text_input("Charge Reward (c/kWh)", value=reward, key=f"ev_rew_{idx}")
            
            plug_ent = st.text_input("EV Plugged In Entity ID", value=plug_ent, key=f"ev_avail_{idx}")

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
            "capacity_kwh": cap, "max_charge_power_entity_id": max_p,
            "min_charge_power_kw": min_p, "min_limit": min_lim,
            "max_limit": max_lim, "charge_reward_cents_per_kwh": reward,
            "volume_l": vol, "temp_min": tmin, "temp_max": tmax,
        })

col_act1, col_act2 = st.columns(2)
add_row = col_act1.button("Add row", use_container_width=True)
save = col_act2.button("Save optional loads", type="primary", use_container_width=True)

if add_row:
    st.session_state.optional_load_rows = edited_rows + [{"name": "", "power_entity_id": "", "load_type": "ev"}]
    st.rerun()

if save:
    optional_loads.save_optional_loads(edited_rows)
    st.session_state.optional_load_rows = optional_loads.load_optional_loads()
    st.success("Optional loads saved. These are stored under /data so they persist across add-on updates.")