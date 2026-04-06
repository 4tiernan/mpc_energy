# MPC Energy
A profit optimiser for home batteries with wholesale electricity pricing.
<img width="2614" height="1465" alt="image" src="https://github.com/user-attachments/assets/0f053133-56cd-49b7-815b-8fd2dbcb6717" />

<br/>

##  🚀 Getting Started

- [Click here for onboarding instructions](https://github.com/4tiernan/mpc_energy/blob/main/docs/ONBOARDING.md)
<br/>

## 📚 Additional Documentation
- To find out more about what all the MQTT sensors and how the system opperates, please view the Descrition docuement [here](https://github.com/4tiernan/mpc_energy/blob/main/docs/DESCRIPTION.md)

<br/>

## FAQ
- If you're having issues or the controller is doing something weird, please view the FAQ's [here](https://github.com/4tiernan/mpc_energy/blob/main/docs/FAQ.md)

<br/>

## ⚠️ Important Safety Notice

This home assitant app automatically controls energy systems such as batteries, inverters, and grid import/export.

While it is designed to be conservative and safe-by-default, it can still make decisions that appear incorrect, suboptimal, or outright dumb due to any number of reasons, including:

* Bad, stale, or missing forecasts (price, solar, load)

* Incorrect configuration or unrealistic constraints

* Edge cases in optimisation logic

* Plain old bugs

As a result, the integration may:

* Charge or discharge the battery and import or export at unexpected times

* Increase energy costs

This app will by design utilise your battery to attempt to decrease electricity costs. This will increase wear on your battery.

Do not rely on this app as your sole safety mechanism.

### You are responsible for:

* Verifying configuration

* Monitoring behaviour

* Ensuring any values configured are reasonable and safe

The software is provided as-is, without warranty of any kind.

[![Open your Home Assistant instance and show the add app repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2F4tiernan%2Fmpc_energy)

## 🤝 Contributing
Contributions are welcome! Whether you're fixing bugs, improving the optimisation logic, or enhancing documentation, please feel free to open a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

## 📄 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.