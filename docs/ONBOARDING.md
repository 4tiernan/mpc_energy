# MPC Energy Onboarding Guide

Welcome to **MPC Energy**, a Home Assistant app that optimizes home battery control based on [Amber](https://www.amber.com.au/) wholesale electricity pricing. This guide will walk you through installation, configuration, and first-time setup.

## Prerequisites
You must use Amber Electric as your electricity retailer to use this app.<br>
To utilise this Home Assistant App you will need the following accounts:
* [Amber Electric](https://www.amber.com.au/)
* [Solcast Home User](https://toolkit.solcast.com.au/register)

Please create these accounts before continuing with the onboarding process.<br><br>
You will also need [HACS](https://www.hacs.xyz/) setup to install the required integrations

## Warning ⚠️: Do not add your device to amber or sign up to the smartshift automation. This will result in you loosing the ability to control your battery system and it can be a lengthy process to undo.

<br>


## 1️⃣ Amber API
Amber Wholesale Prices: Open the [Amber Developer](https://app.amber.com.au/developers/?_gl=1*1szghuy*_gcl_au*ODg1NzE4MjA5LjE3NzEzMTY0NTc.*_ga*MTE1ODI1NDY2Ny4xNzcxMzE2NDU3*_ga_YRCQDZ4F7P*czE3NzEzMTY0NTckbzEkZzEkdDE3NzEzMTY0NTkkajU4JGwwJGgw&_ga=2.115523334.1611969294.1771316457-1158254667.1771316457) tab, you will need to enable developer mode in settings if you haven't already.

Click the 'Generate a new Token' button, give it a name and take note of the API key.

<br>

## 2️⃣ Required Integrations
Solcast Solar Forecasting (HACS):
Follow Instructions Provided [here](https://github.com/BJReplay/ha-solcast-solar?tab=readme-ov-file#solcast-requirements).


Home Assistant MQTT
Setup the [MQTT](https://www.home-assistant.io/integrations/mqtt) integration and the required mosquito broker. Keep the MQTT login details handy to enter into the app config.

Sigenergy (HACS)
Setup the [Sigenergy](https://github.com/TypQxQ/Sigenergy-Local-Modbus?tab=readme-ov-file) integration.
**Note: The controls are disabled by default for saftey, please enable them as per the integration's instructions.**

### You will need to enable the following entities in the Sigenergy Integration:
Controls:
* Remote EMS (Controlled by Home Assistant)
* Remote EMS Control Mode

Configuration:
* ESS Backup State of Charge
* ESS Charge Cut-Off State of Charge
* ESS Discharge Cut-Off State of Charge
* ESS Max Charging Limit
* ESS Max Discharging Limit
* Grid Export Limitation
* Grid Import Limitation
* PV Max Power Limit

Diagnostic:
* Available Max Charging Capacity
* Available Max Discharging Capacity
* ESS Rated Charging Power
* ESS Rated Discharging Power



<br>

## 3️⃣ Installation

### Add the repository
[![Open your Home Assistant instance and show the add app repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2F4tiernan%2Fmpc_energy)
Click the button above or follow the instructions below:

1. Open **Home Assistant → Settings → Add-on Store → ⋮ → Repositories**.
2. Add the following URL:  `https://github.com/4tiernan/mpc_energy`
3. Click **Add**.

### Install the add-on

1. Find **MPC Energy** in the HA App Store.
2. Click **Install**.
3. Wait for the installation to complete, (This can take 10+ minutes, especially on a RPI).

<br>

## 4️⃣ Configuring the App
### In the App's Configuration Tab you will find the following settings:<br><br>
### Risk Acknowledgement:
After reading the risks associated with use of this app in the [readme](https://github.com/4tiernan/mpc_energy?tab=readme-ov-file#%EF%B8%8F-important-safety-notice), confirm you accept and understand them by switching on the accept terms switch in the configuration tab.
<br><br>
### Credentials:
Enter your Amber API key, MQTT username and password as setup before.
<br><br>
### Amber Site ID: 
Start the app without configuring this if you don't know your site id. After starting the app check the logs and select your site id from the list returned by amber and enter it in the configuration.
<br><br>

### Battery Discharge Cost:
If you desire, you may set the battery discharge cost according to the cost of your battery (not solar, inverter or other included system costs) divided by the total discharge energy the battery is warranted for. This ensures the battery will only be used when it makes financial sense to do so. You can set this value higher or lower to adjust the system behaviour though.
<br><br>

### System Limits:
Some of the system limits are exposed by the Sigenergy Integration but a few are not.

The PV Max Power Limit is the 'Max. PV power' listed under DC Input for your inverter model: <br>
[Single Phase](https://www.sigenergy.com/uploads/en_download/1729071058291440.pdf)<br>
[Three Phase](https://www.sigenergy.com/uploads/en_download/1693469427819336.pdf)<br>

The Max Import Power is limited by your main breaker rating (A - Amps).
* Single Phase Max Power (kW): (230 X A) / 1000
* Three Phase Max Power (kW): (3 X 230 X A) / 1000

Round this number down a bit to allow for some headroom, 10% should do, more if you find your breaker is popping.<br>

Examples:
* Single Phase 63A: 14 kW
* Single Phase 80A: 17 kW
* Single Phase 100A: 20 kW
* Three Phase 32A: 20 kW
* Three Phase 63A: 40 kW
* Three Phase 80A: 50 kW

<br>
The Max Export Power is set by your inverter max AC power or you connection export limit. This is normally 5kW per phase, ie, 5 kW for Single Phase or 15 kW for three phase.

<br><br>

## 5️⃣ Starting the Add-on

1. Open the MPC Energy add-on page.
2. Enable **Start on boot** and the **watch dog**
3. Click **Start**.
4. Verify logs to ensure the app starts correctly. If the app throws an error regarding an entity, check that the default entity exists and if not correct it according. If the app throws another error check the FAQs and issues to try and resolve, else create a issue to get it looked into.

<br>

## 6️⃣ Data Visualisation

MPC Energy uses **Streamlit** for its web interface:

1. Access via **Open Webui** from the add-on page. Or add it to the sidebar
2. This interface shows:
   - Real-time battery, solar, and grid metrics
   - Forecasted optimization
3. Validate the plotted data is feasible for your system, if it's not, check all the relevant entities in the configuration.


### Sunsynk Power Flow Card
slipx06 has created a wonderful card to be able to display all relevant data for your energy system. The hacs repo can be found [here](https://github.com/slipx06/sunsynk-power-flow-card) or you can add it to your Home Assitant instance here -> [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=slipx06&repository=sunsynk-power-flow-card&category=plugin)

.<br>
An example yaml for a Sigenergy system can be found 
<a href="https://github.com/4tiernan/mpc_energy/blob/main/yaml_examples/sunsynk_power_flow_card_example.yaml"  target="_blank" rel="noreferrer noopener">here</a>.

### Example Dashboard
An example dashboard showing all the relevant MPC Energy App and Sigenergy Integration entites can be found [here](https://github.com/4tiernan/mpc_energy/blob/main/yaml_examples/mpc_energy_dashboard.yaml).

<br>


## 7️⃣ MQTT Discovery
All the sensors from the app should automatically be discovered by the MQTT integration. Check for a new device in the MQTT integration to see the sensors reported by the MPC Energy app.

**mqtt sensor description**

<br>

## 8️⃣ Troubleshooting
  
- **Missing sensors** → verify all entity_ids are correct.  
- **MQTT not publishing** → check HA broker credentials.  
- **Streamlit not loading** → check app logs and Supervisor logs.

<br>

## 9️⃣ Support
- Most of the logs will show in the app's log tab, otherwise look in the home assistant logs and select supervisor rather than core in the top right.
- GitHub: [https://github.com/4tiernan/mpc_energy](https://github.com/4tiernan/mpc_energy)  
- Issues: Use the GitHub Issues page for bug reports and feature requests.
