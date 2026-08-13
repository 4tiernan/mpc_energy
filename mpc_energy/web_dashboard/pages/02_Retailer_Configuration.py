import streamlit as st
import config_manager
import json
import os
from datetime import datetime
from web_dashboard.common import render_sidebar

st.set_page_config(page_title="Retailer Configuration", layout="wide", initial_sidebar_state="collapsed")
render_sidebar()

st.title("⚡ Retailer Configuration")

config = config_manager.load_config()

retailer = st.selectbox("Select Energy Retailer", ["amber", "flow", "generic"], 
                        index=0 if config.get("energy_retailer") == "amber" else (1 if config.get("energy_retailer") == "flow" else 2))

new_config = {"energy_retailer": retailer}

if retailer == "amber":
    st.subheader("Amber Electric Settings")
    new_config["amber_api_key"] = st.text_input("Amber API Key", value=config.get("amber_api_key", ""), type="password", help="Your Amber API key. You can find this in the developer settings on the Amber Electric website (not the App).")
    new_config["amber_site_id"] = st.text_input("Amber Site ID (Leave blank to discover in logs)", value=config.get("amber_site_id", ""), help="The site ID for your Amber Electric installation. This can be found in the logs after the integration starts.")

elif retailer == "flow":
    st.subheader("Flow Power Settings")
    new_config["flow_import_price_entity_id"] = st.text_input("Import Price Entity ID", value=config.get("flow_import_price_entity_id", ""), help="The Home Assistant entity ID for your Flow Power import price (c/kWh) (IE. sensor.flow_power_qld1_import_price but check your flow integration entity id).")
    new_config["flow_export_price_entity_id"] = st.text_input("Export Price Entity ID", value=config.get("flow_export_price_entity_id", ""), help="The Home Assistant entity ID for your Flow Power export price (c/kWh) (IE. sensor.flow_power_qld1_export_price but check your flow integration entity id).")
    new_config["flow_price_forecast_entity_id"] = st.text_input("Price Forecast Entity ID", value=config.get("flow_price_forecast_entity_id", ""), help="The Home Assistant entity ID for your Flow Power price forecast. (IE. sensor.flow_power_qld1_price_forecast but check your flow integration entity id).")

elif retailer == "generic":
    st.subheader("Generic TOU Settings")
    st.caption("Define time-of-use windows and prices. Times are in HH:MM 24-hour format. End times are inclusive and windows must cover the day continuously with no gaps.")

    # Import windows
    import_windows_count = st.number_input("Number of import windows (daily)", min_value=1, max_value=12, value=max(1, len(json.loads(config.get("generic_import_windows", "[]")) if config.get("generic_import_windows") else [])))
    import_windows = []
    existing_import = json.loads(config.get("generic_import_windows", "[]")) if config.get("generic_import_windows") else []
    for i in range(int(import_windows_count)):
        col1, col2, col3 = st.columns([2,2,1])
        start_val = existing_import[i].get("start") if i < len(existing_import) else ("00:00")
        end_val = existing_import[i].get("end") if i < len(existing_import) else ("23:59")
        price_val = existing_import[i].get("price") if i < len(existing_import) else ("0")
        start = col1.text_input(f"Import Window {i+1} Start (HH:MM)", value=start_val)
        end = col2.text_input(f"Import Window {i+1} End (HH:MM)", value=end_val)
        price = col3.text_input(f"Price (c/kWh)", value=str(price_val), key=f"import_window_{i}_price")
        import_windows.append({"start": start, "end": end, "price": price})
    new_config["generic_import_windows"] = json.dumps(import_windows)

    # Export windows
    export_windows_count = st.number_input("Number of export windows (daily)", min_value=1, max_value=12, value=max(1, len(json.loads(config.get("generic_export_windows", "[]")) if config.get("generic_export_windows") else [])))
    export_windows = []
    existing_export = json.loads(config.get("generic_export_windows", "[]")) if config.get("generic_export_windows") else []
    for i in range(int(export_windows_count)):
        col1, col2, col3 = st.columns([2,2,1])
        start_val = existing_export[i].get("start") if i < len(existing_export) else ("00:00")
        end_val = existing_export[i].get("end") if i < len(existing_export) else ("23:59")
        price_val = existing_export[i].get("price") if i < len(existing_export) else ("0")
        start = col1.text_input(f"Export Window {i+1} Start (HH:MM)", value=start_val)
        end = col2.text_input(f"Export Window {i+1} End (HH:MM)", value=end_val)
        price = col3.text_input(f"Price (c/kWh)", value=str(price_val), key=f"export_window_{i}_price")
        export_windows.append({"start": start, "end": end, "price": price})
    new_config["generic_export_windows"] = json.dumps(export_windows)
st.divider()
st.subheader("Demand Tariff (Optional)")
st.caption("Enter times in 24-hour HH:MM format.")
new_config["demand_price"] = st.text_input("Demand Price ($/kW)", value=config.get("demand_price", ""), help="This is the price per kW (not kWh) of peak demand during the demand window. (only if you have a demand tariff)")

if retailer in ["flow", "generic"]:
    col1, col2 = st.columns(2)
    new_config["demand_window_start"] = col1.text_input("Window Start (HH:MM)", value=config.get("demand_window_start", "16:00"), help="The start time of the demand window.")
    new_config["demand_window_end"] = col2.text_input("Window End (HH:MM)", value=config.get("demand_window_end", "21:00"), help="The end time of the demand window.")

if st.button("Save Retailer Configuration"):
    errors = []
    # Validate Generic TOU windows when generic retailer selected
    if retailer == "generic":
        def validate_windows(windows, label):
            errs = []
            minutes = [False] * 1440
            for idx, w in enumerate(windows):
                s = (w.get("start") or "").strip()
                e = (w.get("end") or "").strip()
                p = (w.get("price") or "").strip()

                # Validate time format
                try:
                    s_dt = datetime.strptime(s, "%H:%M")
                except Exception:
                    errs.append(f"{label} window {idx+1}: invalid start time '{s}'")
                    continue
                try:
                    e_dt = datetime.strptime(e, "%H:%M")
                except Exception:
                    errs.append(f"{label} window {idx+1}: invalid end time '{e}'")
                    continue

                # Validate price
                try:
                    _p = float(p)
                except Exception:
                    errs.append(f"{label} window {idx+1}: invalid price '{p}'")
                    continue

                s_min = s_dt.hour * 60 + s_dt.minute
                e_min = e_dt.hour * 60 + e_dt.minute

                if s_min == e_min:
                    errs.append(f"{label} window {idx+1}: start and end times cannot be identical; use a boundary like 15:59 to 16:00 instead")
                    continue

                # Mark minutes and detect overlap. End times are inclusive, so
                # adjacent windows like 15:59-16:00 and 16:01-16:00 are allowed,
                # while 16:00-16:00 or any gap between windows is rejected.
                if s_min < e_min:
                    rng = range(s_min, e_min + 1)
                else:
                    rng = list(range(s_min, 1440)) + list(range(0, e_min + 1))

                for m in rng:
                    if minutes[m]:
                        errs.append(f"{label} window {idx+1} overlaps another {label.lower()} window")
                        break
                    minutes[m] = True

            if not errs and not all(minutes):
                errs.append(f"{label} windows must cover the full day with no gaps")

            return errs

        errors += validate_windows(import_windows, "Import")
        errors += validate_windows(export_windows, "Export")

    if errors:
        for err in errors:
            st.error(err)
        st.error("Fix the errors above before saving.")
    else:
        config_manager.save_local_config(new_config)
        st.success("Configuration saved. Changes will take effect after restarting the add-on; you can continue configuring other pages and restart when ready.")
        st.session_state["retailer_saved"] = True

if st.session_state.get("retailer_saved"):
    next_step = config_manager.get_next_setup_step()
    if next_step and next_step != "pages/02_Retailer_Configuration.py":
        if st.button(f"Proceed to {config_manager.get_page_title(next_step)}"):
            st.session_state["retailer_saved"] = False
            st.switch_page(next_step)
    else:
        if st.button("🔄 Restart Now", help="Restart the integration to apply changes. You may also restart later when finished configuring other pages."):
            config_manager.trigger_restart()
            st.info("Restarting...")
