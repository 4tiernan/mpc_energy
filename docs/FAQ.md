# Frequently Asked Questions

#### 1. How does the MPC Energy App know how much power my house uses to ensure I don't run out of power over night?
  MPC Energy gets the last few days of your house power consumption through the Sigenergy Local Modbus integration and averages the power consumption to predict your usage. This basic load forecasting is planned on being improved in the future.

#### 2. Can I set a minimum price to dispatch the battery at?
   Yes, but be carefull, in the configuration there is an entry to set the effective cost of discharging the battery. This value defaults to 7c/kWh which means discharging the battery costs 7c/kWh. This will tell the controller to only use the battery when doing so will provide at least this much benefit. IE if the buy price is below this value, don't use the battery just buy from the grid if solar is insufficent, or if its above this value, selling to the grid is permitted.

#### 3. Its the middle of the day and my battery is almost full, yet the controller is using power from the grid?
   The controller will always select to supply the load from the cheapest source of energy, solar has a cost of 0c/kWh and the discharging the battery has a user configurable cost (default 7c/kWh). During the middle of the day it is not uncommon to see buy prices below the battery discharge value, so to reduce unnessesary battery wear, the controller will elect to buy power from the grid when solar power is not sufficent to meet the load demand provided the buy price is less than the battery discharge cost.

#### 4. The controller dumped all my battery in the afternoon and now its using grid power overnight, why did it do this?
   The controller will take into account the cost of using power from the grid vs the profit from selling more power. If the Feed In price (sell price) in the afternoon / evening is greater than the General Price (buy price) overnight, the controller sees that it is more profitable to dispatch the battery now and just run on grid overnight, thus describing this behaviour. 

Note: If your site is on a demand tarrif, provided you have entered the demand tarrif price ($ / kW peak, not $ / kWh) in the appropriate config entry, the controller will take this into account if it plans on buying power overnight. In order for the controller to plan on buying power during the demand window the sell price must be greater than the expected demand window charge, otherwise it will likely leave just enough energy in the battery to supply the load during the demand window then use from the grid overnight. 


#### 5. The controller forecasts a large profit for the day but it doesn't eventuate. 
The controller uses the Amber price forecasts to estimate profit remaing today and tomorrow. Unfortunately these forecasts are not very accurate, especially when forecasting more than an hour or so into the future. Thus, unfortunately there is not much we can do to improve this.

##### Please feel free to pop an issue in with the documentation label if you have issues with something and we can try to improve the docs to help others out who come accross the same issue. 
