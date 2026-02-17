# MPC Energy Onboarding Guide

Welcome to **MPC Energy**, a Home Assistant app that optimizes home battery control based on [Amber](https://www.amber.com.au/) wholesale electricity pricing. This guide will walk you through installation, configuration, and first-time setup.

---

## 1️⃣ Amber API

Amber Wholesale Prices: Open the [Amber Developer](https://app.amber.com.au/developers/?_gl=1*1szghuy*_gcl_au*ODg1NzE4MjA5LjE3NzEzMTY0NTc.*_ga*MTE1ODI1NDY2Ny4xNzcxMzE2NDU3*_ga_YRCQDZ4F7P*czE3NzEzMTY0NTckbzEkZzEkdDE3NzEzMTY0NTkkajU4JGwwJGgw&_ga=2.115523334.1611969294.1771316457-1158254667.1771316457) tab, you will need to enable developer mode in settings if you haven't already.

Click the 'Generate a new Token' button, give it a name and take note of the API key.

---

## 2️⃣ Required Integrations
Solcast Solar Forecasting:
Follow Instructions Provided [here](https://github.com/BJReplay/ha-solcast-solar?tab=readme-ov-file#solcast-requirements).

Home Assistant MQTT
Setup the [MQTT](https://www.home-assistant.io/integrations/mqtt) integration and the required mosquito broker. Keep the MQTT login details handy to enter into the app config.

Sigenergy 
Setup the [Sigenergy](https://github.com/TypQxQ/Sigenergy-Local-Modbus?tab=readme-ov-file) integration.
# Note
The controls are disabled by default for saftey, please enable them as per the integration's instructions.

---

## 3️⃣ Installation

### Add the repository
[![Open your Home Assistant instance and show the add app repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2F4tiernan%2Fmpc_energy)
Click the button above or follow the instructions below:

1. Open **Home Assistant → Settings → Add-on Store → ⋮ → Repositories**.
2. Add the following URL:  
   `https://github.com/4tiernan/mpc_energy`
3. Click **Add**.

### Install the add-on

1. Find **MPC Energy** in the HA App Store.
2. Click **Install**.
3. Wait for the installation to complete.

---

## 4️⃣ Configuring the App
Risk Acknowledgement:
After reading the risks associated with use of this app in the readme, check this button to active the app.

Enter your Amber API key, MQTT username and password and set the plant Solar PV DC, import and export limit with the values for your system. 

If you are noticing your main house, gateway or battery breakers are popping from over current, reduce the import/export limits to reduce the max power through these breakers.

Amber Site ID: 
Start the app without configuring this if you don't know your site id. After starting the app check the logs and select your site id from the list returned by amber and enter it in the configuration.


Battery Discharge Cost:
If you desire, you may set the battery discharge cost according to the cost of your battery (not solar, inverter or other included system costs) divided by the total discharge energy the battery is warranted for. This ensures the battery will only be used when it makes financial sense to do so. You can set this value higher or lower to adjust the system behaviour though.



## 5️⃣ Starting the Add-on

1. Open the MPC Energy add-on page.
2. Enable **Start on boot** and the **watch dog**
3. Click **Start**.
4. Verify logs to ensure the app starts correctly. If the app throws an error regarding an entity, check that the default entity exists and if not correct it according. If the app throws another error check the FAQs and issues to try and resolve, else create a issue to get it looked into.

---

## 6️⃣ Web Interface

MPC Energy uses **Streamlit** for its web interface:

1. Access via **Open Webui** from the add-on page. Or add it to the sidebar
2. This interface shows:
   - Real-time battery, solar, and grid metrics
   - Forecasted optimization
3. Validate the plotted data is feasible for your system, if it's not, check all the relevant entities in the configuration.

---


## 7️⃣ MQTT Discovery
All the sensors from the app should automatically be discovered by the MQTT integration. Check for a new device in the MQTT integration to see the sensors reported by the MPC Energy app.

**mqtt sensor description**

---

## 8️⃣ Troubleshooting
  
- **Missing sensors** → verify all `entity_id`s are correct.  
- **MQTT not publishing** → check HA broker credentials.  
- **Streamlit not loading** → check app logs and Supervisor logs.

---

## 9️⃣ Support

- GitHub: [https://github.com/4tiernan/mpc_energy](https://github.com/4tiernan/mpc_energy)  
- Issues: Use the GitHub Issues page for bug reports and feature requests.
