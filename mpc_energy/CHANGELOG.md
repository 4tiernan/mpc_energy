## 0.6.0
* Adding flow power as retailer option

## 0.5.0
* Increased MPC forecast horizon to 72hrs
* Implemented warm start for MPC to improve solve time (for RPI, solve times went from 25 sec to <1 sec!! with 48hr horizon, approx 1-2 sec for 72hr)
* Added price forecast uncertainty consideration in MPC plan.
* Fixed issue causing battery discharge cost input not adjusting MPC behaviour
* Added SolCast day 3 and 4 forecast to configuration page (required for 72hr forecast, please enable these entities in the solcast integration)
* Improved solar EOD detection and vailidation
* Improved Streamlit refresh rate to line up with MPC data update rate
* Increased Amber forecast horizon to use as much as the API returns (can vary between 12-48 hours).
* Added Amber API Site ID check
* Fixed issue where prices didn't update after HA restart
* Added configurable log level
* Fixed issue when MPC started with Remote EMS off the system would fail to start
* Reduced delay when retrieving new price
* Stopped profit sensor calculations from throwing error at midnight
* Added historical data caching for profit sensor (reduced sensor update time from 11s to <0.1s)
* Added persistent HA notification if error occours
* Added mobile notifications for error and spike as well as a HA persistent notification for spikes
* Major decrease to loading time for MPC plot on Streamlit dashboard (23 sec to 5 sec on RPI)

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