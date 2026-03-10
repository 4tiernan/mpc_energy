## 0.3.0
* Added manual control option with price change trigger
* Improved Amber API auth logging
* Added fallback to safemode when error occours or Amber price remains estimated for more than 5 minutes
* Improved missing load data detection and repair
* Checking required entities before full     startup


## 0.2.50
* Added new sensors for forecast daily profit
* Added Timezone awareness
* Fixed bug where demand window and forecast prices weren't lined up to the correct timestamps when more than 1 hr in the future
* Improved error handling during inital setup
* Corrected spelling for 'remote ems controlled by home assistant' from 'controled' in line with the Sigenergy Integration update for the config defaults
* Changed main loop to 10 seconds from 2 seconds and improved efficency
* Implemented MQTT sensors for Control Mode Override feature (full implementation coming next release)