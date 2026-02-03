# MPC Energy
A profit optimiser for home batteries with wholesale electricity pricing.
<br/>
<br/>
## ⚠️ Important Safety Notice

This integration automatically controls energy systems such as batteries, inverters, and grid import/export.

While it is designed to be conservative and safe-by-default, it can still make decisions that appear incorrect, suboptimal, or outright dumb due to:

* Bad, stale, or missing forecasts (price, solar, load)

* Sensor errors or delayed updates

* Incorrect configuration or unrealistic constraints

* Edge cases in optimisation logic

* Plain old bugs

As a result, the integration may:

* Charge or discharge at unexpected times

* Fail to correctly utilise the battery

* Export energy when you would prefer it not to

* Increase energy costs

Do not rely on this integration as your sole safety mechanism.

### You are responsible for:

* Verifying configuration

* Monitoring behaviour

* Setting sensible limits in your inverter and battery systems

The software is provided as-is, without warranty of any kind.
