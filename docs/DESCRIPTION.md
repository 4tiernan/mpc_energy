# MQTT sensors and MPC plot data points

This document lists:

1. All MQTT entities created by the app for Home Assistant discovery (with a focus on sensors).
2. Every data point expected in the MPC plot payload published to MQTT and plotted in the Streamlit Dashboard.

---

## MQTT overview

- **Home Assistant sensors/controls:** created through `ha_mqtt_discoverable` under device **MPC Energy Manager Device** with the prefix `mpc_energy_manager` applied to each `unique_id`.

- **MPC plot output topic:** `home/mpc/output` (JSON, retained).  

---

## MQTT sensors (Home Assistant discovery)

| HA display name | Unit | Value source / meaning |
|---|---|---|
| Base Load | `w` | Estimated base load as the 20th percentile load value. |
| Alive Time | `s` | App uptime in seconds. |
| Working Mode | — | Current operating mode string. |
| System State | — | Compact summary string: mode, grid flow (with E or I for export or import), price and daily profit. |
| Effective Price | `c/kWh` | Current effective cost of using electricity at this moment, use this value to control automations. <br>I.E. Charge the EV if the price is < 10 c/kWh. |
| Feed In Price | `c/kWh` | Current Amber feed-in price. |
| General Price | `c/kWh` | Current Amber import/general price. |
| Remaining API Calls | `calls` | Amber API remaining call count. |
| Max Forecasted 12hr Feed In | `c/kWh` | Forecast max feed-in price in next 12h. |
| Import Costs Today | `$` | Accumulated import cost today. |
| Export Profits Today | `$` | Accumulated export profit today. |
| Net Profits Today | `$` | Net daily profit. (Negative indicates a net cost, excludes daily usage and Amber fees)|
| Profit Remaining Today | `$` | MPC forecast additional profit remaining for current day. |
| Profit Tomorrow | `$` | MPC forecast profit for tomorrow. |
| Target Discharge Price | `c/kWh` | RBC target dispatch/discharge price threshold (Not used for MPC controller). |
| kWh Discharged | `kWh` | Energy required to charge to full. |
| kWh Remaining | `kWh` | Available stored energy (backup energy excluded). |
| kWh Required Overnight | `kWh` | Estimated overnight energy requirement (with inflation). |
| kWh Till Sundown | `kWh` | Estimated required energy until sundown (6pm hard coded, used for RBC only). |
| Average Daily Load | `kWh` | Average daily load estimate (no inflation). |
| Estimated Price | — | 0/1 style status indicating if Amber failed to provide a real price after it was expected (Their API occasionally fails to get the prices from AEMO). |
| Curtailment Status | — | 0/1 status if system is curtailing. |
| Curtailment Limit | — | Curtailment reason and solar kW limit. |

---

## Other MQTT entities (not sensors)

These are MQTT-discovered controls and are still relevant when auditing MQTT entities:

- **Switch:** `Automatic Control` this switch allows MPC Energy to control your system, if off, MPC Energy will just read data and plot with no action.
- **Select:** `Energy Controller` with options `MPC`, `RBC`, `Safe Mode`.
- **Select:** `Control Mode Override` allows you to manually override the control mode, (this will be set back to disabled once the override has finished).
- **Select:** `Control Mode Override Duration` sets the duration of the control mode override to 5, 15, 30 or 60 minutes or until the relevant price changes.

---

## Controller options explained (MPC / RBC / Safe Mode)

The **Energy Controller** selector exposes three top-level controller options:

- **Safe Mode**: A conservative fallback state that aims to minimise avoidable grid interaction. It does not intentionally export and only imports once the battery is depleted. Use this mode if data quality is poor or controller behaviour appears abnormal.
- **RBC (Rule Based Control)**: Uses deterministic IF/ELSE style rules to pick control actions. Behaviour is predictable and generally conservative; it can export when conditions suit but prohibits grid import until battery energy is depleated.
- **MPC (Model Predictive Control)**: Solves an optimisation over the forecast horizon (prices, load, solar, constraints) and selects the control plan that optimises expected economic outcome. This is the most primary mode and yeilds the greatest overall performance and is the recommended controller.

---

## Working modes explained

The app uses these control modes (shown in the **Working Mode** sensor and in `plan_modes` in the MPC output and accessable in the control mode overrider):

- **Self Consumption**: Supplies house load with solar or battery, prohibits any export and only imports if battery is empty.
- **Exporting Excess Solar**: Exports surplus solar once battery is charged or when a limited charge rate is desired.
- **Exporting All Solar**: Exports all solar after supplying the house load.
- **Dispatching**: Discharges battery deliberately to export to grid when price conditions are favourable.
- **Grid Import**: Imports from grid (typically to support load and/or charge battery under favourable import pricing)(This can occour during the day when import price < battery discharge cost and solar power < load power).
- **Solar To Load**: Prohibits export and curtails the solar to match load with no battery charging allowed. (Used when prices are negative)

If the mode cannot be determined for a time slice in the MPC visualisation, it can appear as **Unable to determine** in the control-mode plot legend/order and the system will default to 'Self Consumption'.

---

## MPC plot payload data points (`home/mpc/output`)

The MPC publishes one JSON payload used by Streamlit plotting code. Keys and meanings:

| Payload key | Used in plot/dashboard as | Meaning |
|---|---|---|
| `Time Index` | X-axis | 5-minute interval timeline. |
| `Battery Power` | Row 1 line | Battery power (-Charge, +Discharge), kW. |
| `SOC` | Row 2 line | Battery state of charge trajectory, kWh. |
| `Grid Net` | Row 1 line | Net grid power (+import / -export), kW. |
| `Segment Grid Energy` | Row 3 segment bars | Net grid power per import/export segment (+import / -export), kWh. |
| `Buy Price` | Row 1 right axis | Buy/import prices, c/kWh. |
| `Sell Price` | Row 1 right axis | Sell/feed-in prices, c/kWh. |
| `Effective Buy Price` | Optional legend trace | Effective buy prices used by MPC controller (artifically inflated to represent forecast uncertainty). |
| `Effective Sell Price` | Optional legend trace | Effective sell prices used by MPC (artifically deflated to represent forecast uncertainty). |
| `Profit Already Today` | Top metric | Realized profit so far today, $. |
| `Profit Remaining Today` | Top metric | Forecast remaining profit today (Uses real prices not artificial inflated/deflated prices), $.|
| `Profit Tomorrow` | Top metric | Forecast tomorrow profit (Uses real prices not artificial inflated/deflated prices), $. |
| `Inverter Power` | Row 1 line | Inverter power, kW. |
| `Solar Forecast` | Row 1 line | Forecast solar power, kW. |
| `Solar Used` | Row 1 line | Solar power planned to be used in schedule, kW. |
| `Load Power` | Row 1 line | Forecast site load power, kW. |
| `SOC Min` | Row 2 dashed hline | Minimum SOC constraint, kWh. |
| `SOC Max` | Row 2 dashed hline | Maximum SOC constraint, kWh. |
| `Control Modes` | Row 3 stepped line + background colors | MPC-derived control mode for each interval. |
| `Demand tariff` | Row 2 Red Highlight | Demand-window overlays and peak-demand metric (Only for sites with demand tariff). |
| `Peak Demand`* | Top metric (col 5) | Predicted peak demand in demand window (Only for sites with demand tariff), kW. |

\* Optional keys only added for demand tariff scenarios.

---

## Where this is produced/consumed in code

- **Published:** `MPC.py` publishes the output JSON to `home/mpc/output`.
- **Subscribed:** `webserver.py` subscribes to `home/mpc/output` and stores latest payload in session state.
- **Rendered:** `web_plot.py` reads the payload keys above to build the three-row Plotly chart and top metrics.