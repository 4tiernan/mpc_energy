# MPC Energy Onboarding Guide

Welcome to **MPC Energy**, a Home Assistant add-on that optimizes home battery usage based on wholesale electricity pricing. This guide will walk you through installation, configuration, and first-time setup.

---

## 1️⃣ Installation

### Add the repository

1. Open **Home Assistant → Settings → Add-on Store → ⋮ → Repositories**.
2. Add the following URL:  
   `https://github.com/4tiernan/mpc_energy`
3. Click **Add**.

### Install the add-on

1. Find **MPC Energy** in the Add-on Store.
2. Click **Install**.
3. Wait for the installation to complete.

---

## 2️⃣ Starting the Add-on

1. Open the MPC Energy add-on page.
2. Enable **Start on boot**.
3. Click **Start**.
4. Verify logs to ensure the add-on starts correctly.

---

## 3️⃣ Ingress / Web Interface

MPC Energy uses **Streamlit** for its web interface:

1. Access via **Ingress** from the add-on page.
2. Default port: `8501` (configured automatically by HA).
3. This interface shows:
   - Real-time battery, solar, and grid metrics
   - Forecasted optimization

---

## 4️⃣ Configuration Options

All configuration is handled via the add-on **Options** panel. Here’s what you need to set:

| Option | Description | Example / Notes |
|--------|-------------|----------------|
| `accepted_risks` | Accept MPC experimental features | `false` |
| `log_level` | Level of logs to display | `info`, `debug`, `warning`, `error`, `critical` |
| `ha_mqtt_user` / `ha_mqtt_pass` | Credentials to connect to HA MQTT broker | Leave blank if using discovery |
| `amber_api_key` / `amber_site_id` | Amber electric tariff API credentials | Optional, only if using Amber API |
| `battery_discharge_cost` | $/kWh cost of battery discharge | 7 |
| `battery_max_discharge_power_limit_entity_id` | Sensor for battery max discharge power | `sensor.sigen_plant_ess_rated_discharging_power` |
| `battery_max_charge_power_limit_entity_id` | Sensor for battery max charge power | `sensor.sigen_plant_ess_rated_charging_power` |
| `inverter_max_power_limit_entity_id` | Max power sensor from inverter | `sensor.sigen_plant_max_active_power` |
| `pv_max_power_limit_entity_id` | Max PV generation sensor | optional |
| `import_max_power_limit_entity_id` | Max grid import sensor | optional |
| `export_max_power_limit_entity_id` | Max grid export sensor | optional |
| `solcast_forecast_*` | PV forecast sensors | `sensor.solcast_pv_forecast_forecast_today` etc. |
| `ha_ems_control_switch_entity_id` | EMS control switch | `switch.sigen_plant_remote_ems_controled_by_home_assistant` |
| `ems_control_mode_entity_id` | EMS control mode selector | `select.sigen_plant_remote_ems_control_mode` |
| `load_power_entity_id` | Current load sensor | `sensor.sigen_plant_consumed_power` |
| `solar_power_entity_id` | Solar production sensor | `sensor.sigen_plant_pv_power` |
| `battery_power_entity_id` | Battery power sensor | `sensor.reversed_battery_power` |
| `inverter_power_entity_id` | Inverter power sensor | `sensor.sigen_plant_plant_active_power` |
| `grid_power_entity_id` | Grid power sensor | `sensor.sigen_plant_grid_active_power` |
| `battery_soc_entity_id` | Battery state of charge sensor | `sensor.sigen_plant_battery_state_of_charge` |
| `battery_stored_energy_entity_id` | Stored energy sensor | `sensor.sigen_plant_available_max_discharging_capacity` |
| `battery_kwh_till_full_entity_id` | Remaining charge capacity | `sensor.sigen_plant_available_max_charging_capacity` |
| `plant_solar_kwh_today_entity_id` | Daily solar energy | `sensor.sigen_inverter_daily_pv_energy` |
| `plant_daily_load_kwh_entity_id` | Daily load consumption | `sensor.sigen_plant_daily_load_consumption` |
| `battery_rated_capacity_entity_id` | Rated battery capacity | `sensor.sigen_plant_rated_energy_capacity` |
| `backup_soc_entity_id` | Backup SOC for EMS | `number.sigen_plant_ess_backup_state_of_charge` |
| `charge_cutoff_soc_entity_id` | Charge cutoff SOC | `number.sigen_plant_ess_charge_cut_off_state_of_charge` |
| `battery_discharge_limiter_entity_id` | Battery discharge limit | `number.sigen_plant_ess_max_discharging_limit` |
| `battery_charge_limiter_entity_id` | Battery charge limit | `number.sigen_plant_ess_max_charging_limit` |
| `pv_limiter_entity_id` | PV power limiter | `number.sigen_plant_pv_max_power_limit` |
| `export_limiter_entity_id` | Grid export limiter | `number.sigen_plant_grid_export_limitation` |
| `import_limiter_entity_id` | Grid import limiter | `number.sigen_plant_grid_import_limitation` |

> ⚠️ Make sure each entity exists in Home Assistant; missing sensors may prevent MPC Energy from running properly.

---

## 5️⃣ MQTT Discovery (Optional)

If you enable **MQTT**, MPC Energy will automatically publish entities to Home Assistant:

- Ensure `ha_mqtt_user` and `ha_mqtt_pass` are set if using a secured broker.
- Topics follow: `mpc_energy/<entity_id>`

---

## 6️⃣ First Run

1. Save the configuration in the Options panel.
2. Restart the add-on.
3. Check **Logs**:
   - Ensure all sensors are detected
   - No errors connecting to MQTT or HA API
4. Open the **Streamlit interface** via Ingress.
5. Verify the dashboard shows live battery, solar, and grid data.

---

## 7️⃣ Troubleshooting

- **Add-on fails to start** → check that `arch` matches your device (`aarch64` for RPi4-64).  
- **Missing sensors** → verify all `entity_id`s are correct.  
- **MQTT not publishing** → check HA broker credentials.  
- **Streamlit not loading** → check Ingress port (`8501`) and Supervisor logs.

---

## 8️⃣ Updating

1. Pull latest changes from the repository.
2. Reinstall or rebuild the add-on.
3. Restart add-on to apply updates.

---

## 9️⃣ Support

- GitHub: [https://github.com/4tiernan/mpc_energy](https://github.com/4tiernan/mpc_energy)  
- Issues: Use the GitHub Issues page for bug reports and feature requests.
