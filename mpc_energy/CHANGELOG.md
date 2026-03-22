## 0.5.0
* Improved solar EOD detection and vailidation
* Fixed issue causing battery discharge cost input not adjusting MPC behaviour
* Added price forecast uncertainty consideration in MPC plan.
* Added configurable log level
* Increased Amber forecast horizon to use as much as the API returns (can vary between 12-48 hours).
* Increased MPC forecast horizon to 48hrs
* Added SolCast day 3 forecast to configuration page (required for 48hr forecast)
* Improved Streamlit refresh rate to line up with MPC data update rate
* Fixed issue where prices didn't update after HA restart

## 0.4.0
* Added Solar Curtailment Sensor to show when the system is likely curtailing and why
* Fixed issue where no controller action was taken when controller initalised to MPC after install
* Changed Amber delayed price Safe Mode trigger from 5 to 10 minutes
* Increased MPC grid import penalty and decreased EOD charge reward to reduce unnecessary grid charging 
* Fixed issue where inconsistent Sigenergy load data caused an error
* Fixed bad entity data retrival causing system exit
* Added detection and improved logging if Sigenergy system goes offline
* Fixed issue casuing Streamlit dashboard to get started twice

## 0.3.0
* Added manual control option with price change trigger
* Improved Amber API auth logging
* Added fallback to safemode when error occours or Amber price remains estimated for more than 5 minutes
* Improved missing load data detection and repair
* Checking required entities before full startup
* Inproved management for missing data from Amber API
* Added load data vaildation to stop MPC from failing infeasible 


## 0.2.50
* Added new sensors for forecast daily profit
* Added Timezone awareness
* Fixed bug where demand window and forecast prices weren't lined up to the correct timestamps when more than 1 hr in the future
* Improved error handling during inital setup
* Corrected spelling for 'remote ems controlled by home assistant' from 'controled' in line with the Sigenergy Integration update for the config defaults
* Changed main loop to 10 seconds from 2 seconds and improved efficency
* Implemented MQTT sensors for Control Mode Override feature (full implementation coming next release)