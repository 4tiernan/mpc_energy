import math

import numpy as np
import cvxpy as cp
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import time
from energy_controller import ControlMode
from mpc_logger import logger
import warnings

import json
import paho.mqtt.client as mqtt
import const
import config_manager
from helper_functions import round_minutes

mqtt_client = mqtt.Client()
mqtt_client.username_pw_set(config_manager.MQTT_USER, config_manager.MQTT_PASS) 
mqtt_client.connect(const.MQTT_HOST, const.MQTT_PORT)
mqtt_client.loop_start()

class MPC:
    def __init__(self, ha, plant, EC, local_tz, demand_tarrif, retailer):
        self.plant = plant
        self.ha = ha
        self.EC = EC
        self.local_tz = local_tz
        self.retailer = retailer

        self.power_threshold = 0.2 # Threshold when comparing power values

        self.update_limits()    # Update fixed limits (some are required for config)

        # ---------- Config ----------
        self.forecast_hrs = 72
        self.steps_per_price = 30 // 5  # = 6
        self.steps_per_hr = 60 // 5

        #self.N_5min = self.forecast_hrs * (60 // 5)

        self.load_inflation_percentage = 20 # Percentage to inflate the load forecast by to ensure we don't run out in the morning.

        self.dt_5min = 5/60      # 5 minutes in hours

        # Reward and penalty settings
        self.discharge_efficiency = 0.95
        self.grid_import_penalty_cost = 0.03 # $/kWh penalty for using grid power
        self.full_battery_reward = 0.03  # $/kWh — use this value to encourage the battery to be full by the end of the solar day
        self.charge_maintain_reward = 0.01 / (self.forecast_hrs*self.steps_per_hr*self.battery_capacity) # $/kWh / interval reward for maintaining higher SOC throughout the day, currently equates to 1c total over the whole day
        self.demand_tarrif = demand_tarrif # True if the selected site has a demand tarrif applied
        self.current_effective_price = 0 # Set to zero until we run an optimisation and determine the current effective price based on the MPC plan and current conditions
        


        # User configured values
        self.battery_min_export_cost = config_manager.battery_discharge_cost/100  # $/kWh (Export will only occour ABOVE this value)
        logger.debug(f"Battery discharge cost set to: {self.battery_min_export_cost} $/kWh")
        if(self.battery_min_export_cost < 0 or self.battery_min_export_cost > 1):
            logger.warning(f"Battery discharge cost of {self.battery_min_export_cost} $/kWh seems very high or low, please ensure this value is correct to avoid unexpected behaviour.")

        # Forecast uncertainty tuning. These intentionally bias decisions toward near-term certainty.
        # Set to 0 to disable.
        self.buy_price_uncertainty_premium_per_hour = 1      # +%/hr applied to future buy prices
        self.sell_price_uncertainty_discount_per_hour = 1    # -%/hr applied to future sell prices
        self.max_price_uncertainty_adjustment = 30           # Cap the absolute buy/sell adjustment (+/-30%)

        if(self.retailer == "flow"):
            self.sell_price_uncertainty_discount_per_hour = 0 # Flow sell prices are known with certainty
            # Flow tariffs can include deterministic high export windows (e.g., happy hour).
            # Holding-SOC reward can delay discharge within a flat high-price window, so
            # disable it in Flow mode to prioritise immediate arbitrage when profitable.
            self.charge_maintain_reward = 0
            logger.debug("Flow retailer detected: Disabling sell price uncertainty discount and charge maintain reward to prioritise immediate arbitrage with known prices.")

        logger.debug(f"Forecast uncertainty: Buy premium: {self.buy_price_uncertainty_premium_per_hour} %/hr, Sell discount: {self.sell_price_uncertainty_discount_per_hour} %/hr, Max adjustment: {self.max_price_uncertainty_adjustment} %")
        
        if(self.buy_price_uncertainty_premium_per_hour < 0 or self.buy_price_uncertainty_premium_per_hour > 100):
            logger.warning(f"Buy price uncertainty premium of {self.buy_price_uncertainty_premium_per_hour} %/hr seems very high or low, please ensure this value is correct to avoid unexpected behaviour.")
        if(self.sell_price_uncertainty_discount_per_hour < 0 or self.sell_price_uncertainty_discount_per_hour > 100):
            logger.warning(f"Sell price uncertainty discount of {self.sell_price_uncertainty_discount_per_hour} %/hr seems very high or low, please ensure this value is correct to avoid unexpected behaviour.")
        if(self.max_price_uncertainty_adjustment < 0 or self.max_price_uncertainty_adjustment > 100):
            logger.warning(f"Max price uncertainty adjustment of {self.max_price_uncertainty_adjustment} % seems very high or low, please ensure this value is correct to avoid unexpected behaviour.")

        # Profit Variables
        self.profit_remaining_today = 0
        self.profit_tomorrow = 0

        self.update_forecast_horizon()

        # Build the CVXPY optimisation template once and reuse it on each run.
        # This avoids repeated canonicalization overhead at every control interval.
        self.build_optimisation_template()

    def update_forecast_horizon(self):
        """
        Set the MPC horizon to finish at 06:00 on the next-next-next morning
        in local time (i.e., the third upcoming 06:00 boundary).
        """
        
        now = datetime.now(self.local_tz).replace(second=0, microsecond=0)

        sim_start = round_minutes(time=now, nearest_minute=5) # Round the sim start time to the nearest 5 minutes to ensure the time steps align with the forecast data
        #morning_cutoff = sim_start.replace(hour=6, minute=0)
        #horizon_end = morning_cutoff + timedelta(days=3)  # 3 mornings from now
        horizon_end = sim_start + timedelta(hours=72) # Default to 72 hours from now

        horizon_seconds = max((horizon_end - sim_start).total_seconds(), 300)
        self.sim_start = sim_start
        self.sim_end = horizon_end
        self.N_5min = max(1, int(horizon_seconds // (5 * 60)))
        self.forecast_hrs = self.N_5min * self.dt_5min

        logger.debug(
            f"MPC forecast horizon set to {round(self.forecast_hrs, 2)} hrs "
            f"({self.N_5min}x5min) segments from {self.sim_start.strftime('%Y-%m-%d %H:%M %Z')} "
            f"to {self.sim_end.strftime('%Y-%m-%d %H:%M %Z')}"
        )
             
    def update_limits(self):
        # Battery Settings
        self.battery_capacity = self.plant.rated_capacity  # kWh
        self.soc_min = self.plant.kwh_backup_buffer
        self.soc_max = self.battery_capacity
        
        self.solar_dc_max = self.plant.max_pv_power             # kW (DC limit for MPPTs)
        self.p_max_charge = self.plant.max_charge_power         # kW (Battery max charge rate)
        self.p_max_discharge = self.plant.max_discharge_power   # kW (Battery max discharge rate)
        self.inverter_p_max = self.plant.max_inverter_power     # kW (Inverter power limit)
        self.grid_import_limit = self.plant.max_import_power    # kW (Grid import limit)
        self.grid_export_limit = self.plant.max_export_power    # kW (Grid export limit)      

    # Update any values or forecasts required to run the sim
    def update_values(self, amber_data, inject_real_values = True):
        self.update_limits() # Update the limits in case the user has changed any config values that affect the limits since the last update
        
        current_soc = (self.plant.battery_soc / 100)*self.soc_max
        self.soc_init = min(max(current_soc, self.soc_min), self.soc_max) #constrain the soc to within limits to stop solver from doing weird stuff

        # ---------- Historical Data ---------- 
        #self.historical_data = self.plant.historical_data(hours=6) # Get the last 6 hours of historical data (Primarily used for displaying historical data on plot)
        self.historical_data = self.plant.historical_data(hours=0.25)
        self.daily_profit = self.plant.daily_net_profit
        
        # ---------- Forecasts ----------
        # Load Forecast
        load_power_states = self.plant.forecast_load_power(
            forecast_hours_from_now=self.forecast_hrs,
            forecast_start_time=self.sim_start,
            forecast_end_time=self.sim_end,
        )

        self.load_5min = [powerstate.avg_state*(1+self.load_inflation_percentage/100.0) for powerstate in load_power_states]
        
        
        # Solar Forecast
        self.solar_5min = self.plant.forecast_solar_power(
            forecast_hours_from_now=self.forecast_hrs,
            forecast_start_time=self.sim_start,
            forecast_end_time=self.sim_end,
        )

        # Inject the current real load and solar values into the sim
        if(inject_real_values):
            # Inject the avg of the last 5 minutes of solar and load power
            self.solar_5min[0] = (self.solar_5min[0] + self.historical_data["solar_power"][-1]) / 2 # Avgerage the last 5 minutes of solar with the forecast to make a more realistic value for the current timestep
            self.load_5min[0] = self.historical_data["load_power"][-1] # Inject the current real load power value into the sim (change to 5min avg of the most recent 5min interval if possible)


            # Inject the current instantaneous solar and load values into the sim
            #self.solar_5min[0] = self.plant.solar_kw #change to 5min avg of these instantaneous values
            #self.load_5min[0] = self.plant.load_power
        
        if(max(self.load_5min) > self.grid_import_limit or min(self.load_5min) < 0):
            logger.warning(f"Some load values fall outside of limits, Max Load: {max(self.load_5min)}, Min Load: {min(self.load_5min)}. Clipping to ensure solver feasability, please report this if it occours frequently.")

        self.load_5min = [min(max(load, 0.0), self.grid_import_limit)  for load in self.load_5min] # Don't allow negative load or solar or load greater than import limit
        self.solar_5min = [max(solar, 0.0) for solar in self.solar_5min]

        # Amber Forecast (forecast hrs is set in main.py in the get_data call)
        self.demand_tarrif_price = amber_data.demand_tarrif_price if amber_data.demand_tarrif_price is not None else 0.0
        general_price_forecast = amber_data.general_extrapolated_forecast[:int(self.N_5min)]
        feed_in_price_forecast = amber_data.feedIn_extrapolated_forecast[:int(self.N_5min)]
        self.demand_window_forecast = np.array(amber_data.demand_window_extrapolated_forecast[:int(self.N_5min)], dtype=float)

        # Convert to $/kWh
        self.prices_buy = np.array(general_price_forecast) / 100      # buy price in $ from cents
        self.prices_sell  = np.array(feed_in_price_forecast) / 100      # sell price in $ from cents

        for i in range(len(self.prices_buy)):
            if self.prices_buy[i] < self.prices_sell[i]:
                logger.warning(f"Buy price is below sell price at index {i}, time: {(self.sim_start + timedelta(minutes=5*i)).isoformat()}. Buy price: {self.prices_buy[i]:.4f} $/kWh, Sell price: {self.prices_sell[i]:.4f} $/kWh. This may indicate an issue with the price forecast data. Increasing buy price to be 10c above sell price.")
                self.prices_buy[i] = self.prices_sell[i] + 0.10 # Add a small premium to ensure buy price is above sell price to avoid weird solver behaviour.

        # Build uncertainty-adjusted prices so near-term intervals are valued more than
        # far-future forecast intervals (which are less reliable).
        hours_from_now = np.arange(int(self.N_5min)) * self.dt_5min
        buy_price_uncertainty_factor = np.minimum(
            1 + (hours_from_now * (self.buy_price_uncertainty_premium_per_hour/100)),
            1 + (self.max_price_uncertainty_adjustment/100)
        )
        sell_price_uncertainty_factor = np.maximum(
            1 - (hours_from_now * (self.sell_price_uncertainty_discount_per_hour/100)),
            1 - (self.max_price_uncertainty_adjustment/100)
        )

        self.effective_prices_buy = np.multiply(self.prices_buy, buy_price_uncertainty_factor)
        self.effective_prices_sell = np.multiply(self.prices_sell, sell_price_uncertainty_factor)

        self.effective_prices_sell = self.effective_prices_sell - 0.0001 # Decrease prices slightly to discorage selling at a zero price

        #self.prices_buy[0:5] = 0.03 #Testing
        #self.prices_sell[0:5] = 0.01
        #self.soc_init = 0.95*self.soc_max

    def build_optimisation_template(self):
        n = int(self.N_5min)

        # Variables
        self.p_charge = cp.Variable(n, nonneg=True)
        self.p_discharge = cp.Variable(n, nonneg=True)
        self.soc = cp.Variable(n + 1)
        self.solar_used = cp.Variable(n, nonneg=True)
        self.solar_curtail = cp.Variable(n, nonneg=True)
        self.grid_import = cp.Variable(n, nonneg=True)
        self.grid_export = cp.Variable(n, nonneg=True)
        self.peak_demand = cp.Variable(nonneg=True)
        self.inverter_power = cp.Variable(n)

        # Parameters (updated every run)
        self.soc_init_param = cp.Parameter(nonneg=True, name="soc_init")
        self.solar_forecast_param = cp.Parameter(n, nonneg=True, name="solar_forecast")
        self.load_forecast_param = cp.Parameter(n, nonneg=True, name="load_forecast")
        self.price_buy_param = cp.Parameter(n, name="price_buy")
        self.price_sell_param = cp.Parameter(n, name="price_sell")
        self.demand_mask_param = cp.Parameter(n, nonneg=True, name="demand_mask")
        self.solar_eod_reward_mask_param = cp.Parameter(n, nonneg=True, name="solar_eod_reward_mask")

        self.grid_import_limit_param = cp.Parameter(nonneg=True, name="grid_import_limit")
        self.grid_export_limit_param = cp.Parameter(nonneg=True, name="grid_export_limit")
        self.p_max_charge_param = cp.Parameter(nonneg=True, name="p_max_charge")
        self.p_max_discharge_param = cp.Parameter(nonneg=True, name="p_max_discharge")
        self.inverter_p_max_param = cp.Parameter(nonneg=True, name="inverter_p_max")
        self.solar_dc_max_param = cp.Parameter(nonneg=True, name="solar_dc_max")
        self.soc_min_param = cp.Parameter(nonneg=True, name="soc_min")
        self.soc_max_param = cp.Parameter(nonneg=True, name="soc_max")
        self.demand_peak_price_param = cp.Parameter(nonneg=True, name="demand_peak_price")

        # Vectorized constraints
        constraints = [
            self.soc[0] == self.soc_init_param,
            self.soc[1:] == self.soc[:-1] + self.dt_5min * self.discharge_efficiency * self.p_charge - self.dt_5min / self.discharge_efficiency * self.p_discharge,
            self.soc[1:] >= self.soc_min_param,
            self.soc[1:] <= self.soc_max_param,
            self.p_charge <= self.p_max_charge_param,
            self.p_discharge <= self.p_max_discharge_param,
            self.solar_used <= self.solar_forecast_param,
            self.solar_used <= self.solar_dc_max_param,
            self.solar_used + self.solar_curtail == self.solar_forecast_param,
            self.solar_used + self.p_discharge == self.p_charge + self.inverter_power,
            self.grid_import + self.inverter_power == self.load_forecast_param + self.grid_export,
            self.grid_import <= self.grid_import_limit_param,
            self.grid_export <= self.grid_export_limit_param,
            self.inverter_power <= self.inverter_p_max_param,
            self.inverter_power >= -self.inverter_p_max_param,
            self.peak_demand >= cp.multiply(self.demand_mask_param, self.grid_import),
        ]

        objective_list = (
            cp.multiply(self.grid_import, self.price_buy_param) * self.dt_5min
            - cp.multiply(self.grid_export, self.price_sell_param) * self.dt_5min
            + cp.multiply(self.grid_import, self.grid_import_penalty_cost) * self.dt_5min
            + cp.multiply(self.battery_min_export_cost, self.p_discharge) * self.dt_5min
            - cp.multiply(self.charge_maintain_reward, self.soc[0:-1])
            - cp.multiply(self.full_battery_reward, cp.multiply(self.solar_eod_reward_mask_param, self.soc[0:-1]))
        )

        self.objective_expression = (
            cp.sum(objective_list)
            + self.peak_demand * self.demand_peak_price_param # not summed as it's a single peak charge
        )

        self.prob = cp.Problem(cp.Minimize(self.objective_expression), constraints)

    def run_optimisation(self, amber_data):
        start_optimisation = time.time()

        self.update_values(amber_data)

        now = datetime.now(self.local_tz).replace(second=0, microsecond=0)
        minute = (now.minute // 5) * 5
        now = now.replace(minute=minute)
        time_index = [now + timedelta(minutes=5 * i) for i in range(int(self.N_5min))]

        #logger.error("Messing with prices!!")
        #self.prices_sell[180:] = 0.02 # Allow testing of various pricings
        #self.prices_buy[180:] = 0.05 

        #self.prices_sell[10:65] = 0.0 # Allow testing of various pricings
        #self.prices_buy[10:65] = 0.04
        
        #self.soc_init = self.soc_min
        #self.prices_sell[100:120] = 10 # Allow testing of various pricings
        #self.prices_buy[100:120] = 11

        # Find end of TODAY's solar window (ignore tomorrow's solar)
        # Solar day = first time solar drops to ~0 after having been >0
        today_solar_end_index = None
        tomorrow_solar_end_index = None

        def SolarEODIndexValid(idx):  # Returns true if the solar eod falls between 2pm - 9pm
            t = time_index[idx].time()
            return (14, 0) <= (t.hour, t.minute) <= (21, 0)

        today_date = now.date()
        tomorrow_date = (now + timedelta(days=1)).date()
        # Run backwards from the end of the list to find the last index where solar is significent today.
        for idx in range(int(self.N_5min)-1, -1, -1): 
            if self.solar_5min[idx] > self.load_5min[idx]+ self.power_threshold:      
                if(today_solar_end_index == None and time_index[idx].date() == today_date and SolarEODIndexValid(idx)):
                    today_solar_end_index = idx
                    logger.debug(f"Solar Day today ends at index: {today_solar_end_index}, time: {time_index[today_solar_end_index]}")

                elif(tomorrow_solar_end_index == None and time_index[idx].date() == tomorrow_date and SolarEODIndexValid(idx)):
                    tomorrow_solar_end_index = idx
                    logger.debug(f"Solar Day tomorrow ends at index: {tomorrow_solar_end_index}, time: {time_index[tomorrow_solar_end_index]}")

        # Set parameter values for this optimisation run.
        self.soc_init_param.value = float(self.soc_init)
        solar_forecast_arr = np.array(self.solar_5min, dtype=float)
        load_forecast_arr = np.array(self.load_5min, dtype=float)
        price_buy_arr = np.array(self.effective_prices_buy, dtype=float)
        price_sell_arr = np.array(self.effective_prices_sell, dtype=float)
        if not (len(solar_forecast_arr) == len(load_forecast_arr) == len(price_buy_arr) == len(price_sell_arr) == int(self.N_5min)):
            raise RuntimeError(
                f"Forecast lengths must all equal N_5min ({int(self.N_5min)}), got "
                f"solar={len(solar_forecast_arr)}, load={len(load_forecast_arr)}, "
                f"buy={len(price_buy_arr)}, sell={len(price_sell_arr)}"
            )

        self.solar_forecast_param.value = solar_forecast_arr
        self.load_forecast_param.value = load_forecast_arr
        self.price_buy_param.value = price_buy_arr
        self.price_sell_param.value = price_sell_arr
        self.grid_import_limit_param.value = float(self.grid_import_limit)
        self.grid_export_limit_param.value = float(self.grid_export_limit)
        self.p_max_charge_param.value = float(self.p_max_charge)
        self.p_max_discharge_param.value = float(self.p_max_discharge)
        self.inverter_p_max_param.value = float(self.inverter_p_max)
        self.solar_dc_max_param.value = float(self.solar_dc_max)
        self.soc_min_param.value = float(self.soc_min)
        self.soc_max_param.value = float(self.soc_max)
        demand_mask = np.array((self.demand_window_forecast > 0).astype(float), dtype=float)
        if len(demand_mask) != int(self.N_5min):
            raise RuntimeError(f"Demand mask length ({len(demand_mask)}) must equal N_5min ({int(self.N_5min)})")
        self.demand_mask_param.value = demand_mask
        self.demand_peak_price_param.value = float(self.demand_tarrif_price) if self.demand_tarrif else 0.0

        solar_eod_reward_mask = np.zeros(int(self.N_5min), dtype=float)

        if today_solar_end_index is not None and today_solar_end_index > 0:
            solar_eod_reward_mask[today_solar_end_index] = 1.0 # Encorage the battery to be full by the end of the solar day today

        if tomorrow_solar_end_index is not None and tomorrow_solar_end_index > 0:
            solar_eod_reward_mask[tomorrow_solar_end_index] = 1.0 # Encorage the battery to be full by the end of the solar day tomorrow

        self.solar_eod_reward_mask_param.value = solar_eod_reward_mask # Put the mask into the assigned parameter

        # ---------- Solve ----------
        # Prefer ECOS for speed, but fall back to CLARABEL when ECOS reports an
        # inaccurate solution to avoid propagating unstable plans.
        ecos_inaccurate = False
        with warnings.catch_warnings(record=True) as caught_warnings:
            warnings.simplefilter("always", UserWarning)
            self.prob.solve(solver=cp.ECOS, warm_start=True, max_iters=300) # Increased max iters to allow more time for solving
            ecos_inaccurate = any("Solution may be inaccurate" in str(w.message) for w in caught_warnings)

        if self.prob.status == "optimal_inaccurate" or ecos_inaccurate:
            logger.warning(
                f"ECOS returned {self.prob.status} (inaccurate={ecos_inaccurate}); retrying with CLARABEL."
            )
            self.prob.solve(solver=cp.CLARABEL, warm_start=True)

        # Don't continue if the solver failed
        if self.prob.status not in ("optimal", "optimal_inaccurate"):
            raise RuntimeError(f"MPC solve failed: {self.prob.status}")
        
        else: # Sim successfull 
            # ---------- Results ----------
            battery_power = (self.p_discharge.value - self.p_charge.value).tolist()

            grid_import = self.grid_import.value.tolist()
            grid_export = self.grid_export.value.tolist()
            for i in range(len(grid_import)):
                if grid_import[i] > self.power_threshold and grid_export[i] > self.power_threshold:
                    logger.error(f"Simultaneous import and export detected at index {i}, time: {time_index[i].isoformat()} (import: {grid_import[i]:.2f} kW, export: {grid_export[i]:.2f} kW). This may indicate a problem with the solver or model formulation or buy price is below sell price.")

            grid_net = (self.grid_import.value - self.grid_export.value).tolist()
            #hours = np.arange(int(self.N_5min)) * self.dt_5min

            grid_kwh_import_per_interval = self.grid_import.value / self.steps_per_hr 
            grid_kwh_export_per_interval = self.grid_export.value / self.steps_per_hr 

            # Per-interval profit ($)
            interval_profit = (
                grid_kwh_export_per_interval * self.prices_sell
                - grid_kwh_import_per_interval * self.prices_buy
            )

            today = now.date()
            tomorrow = today + timedelta(days=1)

            forecast_profit_today = 0.0
            forecast_profit_tomorrow = 0.0

            for t, ts in enumerate(time_index):
                if ts.date() == today:
                    forecast_profit_today += interval_profit[t]
                elif ts.date() == tomorrow:
                    forecast_profit_tomorrow += interval_profit[t]

            # Round all the mpc data to 2 dp
            battery_power = [round(x, 2) for x in battery_power]
            battery_soc = [round(x, 2) for x in self.soc.value.tolist()]
            grid_net = [round(x, 2) for x in grid_net]
            inverter_power = [round(x, 2) for x in self.inverter_power.value.tolist()]
            solar_forecast_power = [round(x, 2) for x in self.solar_5min]
            solar_used_power = [round(x, 2) for x in self.solar_used.value.tolist()]
            load_power = [round(x, 2) for x in self.load_5min]

            self.profit_remaining_today = round(float(forecast_profit_today), 2)
            self.profit_tomorrow = round(float(forecast_profit_tomorrow), 2)

            # store it in shared dict
            output = {
                "historical_data_length": 0,
                "time_index": [time_idx.isoformat() for time_idx in time_index],
                "battery_power": battery_power,
                "soc": battery_soc,
                "grid_net": grid_net,
                "demand_tarrif": self.demand_tarrif,
                "prices_buy": self.prices_buy.tolist(),
                "prices_sell": self.prices_sell.tolist(),
                "effective_prices_buy": self.effective_prices_buy.tolist(),
                "effective_prices_sell": self.effective_prices_sell.tolist(),
                "profit_already_today": float(self.daily_profit),
                "profit_remaining_today": self.profit_remaining_today,
                "profit_tomorrow": self.profit_tomorrow,
                "inverter_power": inverter_power,
                "solar_forecast": solar_forecast_power,
                "solar_used": solar_used_power,
                "load_power": load_power,
                "soc_min": self.soc_min,
                "soc_max": self.soc_max,
            }
            output = self.convert_to_python(output) # Ensure all arrays and data is in the plain python format, ie no numpy
            plan_modes = self.determine_plan_modes(output) # Determine the control mode for each time period
            output.update({"plan_modes": plan_modes}) # Add the control modes to the output to be plotted

            if(self.demand_tarrif):
                output.update({
                    "demand_window_forecast": self.demand_window_forecast.tolist(),
                    "peak_demand": float(self.peak_demand.value),
                })

            # Add the historical data to the mpc plan
            plotted_output={}
            '''
            plotted_output = {
                "historical_data_length": len(self.historical_data["time_index"]),
                "time_index": self.historical_data["time_index"] + output["time_index"], 
                "battery_power": self.historical_data["battery_power"] + output["battery_power"],
                "soc": self.historical_data["soc"] + output["soc"],
                "grid_net": self.historical_data["grid_power"] + output["grid_net"],
                "prices_buy": self.historical_data["prices_buy"] + output["prices_buy"],
                "prices_sell": self.historical_data["prices_sell"] + output["prices_sell"],
                "profit_today": float(profit_today),
                "profit_tomorrow": float(profit_tomorrow),
                "inverter_power": self.historical_data["inverter_power"] + output["inverter_power"],
                "solar_forecast": self.historical_data["solar_power"] + output["solar_forecast"],
                "solar_used": self.historical_data["solar_power"] + output["solar_used"],
                "load_power": self.historical_data["load_power"] + output["load_power"],
                "soc_min": self.soc_min,
                "soc_max": self.soc_max,
                "plan_modes": self.historical_data["plan_modes"] + output["plan_modes"],
            }            
            mqtt_client.publish("home/mpc/output", json.dumps(plotted_output), retain=True)'''

            mqtt_client.publish("home/mpc/output", json.dumps(output), retain=True)
        
            self.current_effective_price = self.determine_current_effective_price(output) # Determine the current effective price of electricity based on the MPC plan and current conditions. 

            logger.info(f"Solver took {round(time.time()-start_optimisation,2)} seconds to get data, build and solve. The selected mode is: {output['plan_modes'][0]}")

            return [output, plotted_output]
        
    def convert_to_python(self, obj): # Convert all np objects to python objects
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, dict):
            return {k: self.convert_to_python(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.convert_to_python(v) for v in obj]
        return obj
    
    def determine_control_mode(self, data, increment=0, control_active=True):
        inverter_power = data["inverter_power"][increment]
        used_solar_power = data["solar_used"][increment]
        solar_available = data["solar_forecast"][increment]
        load_power = data["load_power"][increment]
        grid_net = data["grid_net"][increment] # if grid_net is positive we are importing power 
        battery_power = data["battery_power"][increment]

        if((approx_equal(inverter_power, used_solar_power) and used_solar_power > load_power + self.power_threshold and grid_net < -self.power_threshold) or (approx_equal(inverter_power, self.plant.max_inverter_power) and used_solar_power > self.plant.max_inverter_power)):
            if(control_active):
                self.EC.export_all_solar() # Export if all solar is being exported or > max inverter and charging bat with excess
            return ControlMode.EXPORT_ALL_SOLAR.value
        
        elif(approx_equal(inverter_power, load_power) and approx_equal(load_power, used_solar_power) and used_solar_power + self.power_threshold < solar_available):
            if(control_active):
                self.EC.solar_to_load() # If battery is not charging and solar is being curtailed, send solar straight to load
            return ControlMode.SOLAR_TO_LOAD.value
        
        elif(approx_equal(inverter_power, load_power) and approx_equal(used_solar_power+battery_power, load_power)):
            if(control_active):
                self.EC.self_consumption()
            return ControlMode.SELF_CONSUMPTION.value                
        
        elif(inverter_power > used_solar_power + self.power_threshold and inverter_power > load_power + self.power_threshold):
            if(control_active):
                export_limit = abs(grid_net)
                if(approx_equal(inverter_power, self.inverter_p_max)): # If Inverter is at 100% in the plan make sure it is in reality
                    export_limit = self.grid_export_limit
                
                self.EC.dispatch(grid_export_limit = export_limit)
            return ControlMode.DISPATCH.value
        
        elif(grid_net < -self.power_threshold and used_solar_power > inverter_power + self.power_threshold):
            if(control_active):
                self.EC.export_excess_solar(battery_charge_limit = abs(battery_power))
            return ControlMode.EXPORT_EXCESS_SOLAR.value
        
        elif(grid_net > self.power_threshold): # if grid_net is positive we are importing power
            if(control_active):
                self.EC.import_power(battery_charge_limit = abs(battery_power))
            return ControlMode.GRID_IMPORT.value
        
        elif(inverter_power < 0 and battery_power < self.power_threshold):
            if(control_active):
                self.EC.import_power(battery_charge_limit = abs(battery_power), pv_limit = used_solar_power)
            return ControlMode.GRID_IMPORT.value

        else:
            if(control_active):
                self.EC.self_consumption()
                raise Exception("Unable to determine control mode from MPC plan. Selected self consumption for saftey")
            return "Unable to determine"
        
    def determine_plan_modes(self, output): # Determine the control modes for the whole plan
        plan_modes = []
        for i in range(len(output["inverter_power"])):
            mode = self.determine_control_mode(output, increment=i, control_active=False)
            plan_modes.append(mode)
        return plan_modes

    def run(self, amber_data):
        [output, plotted_output] = self.run_optimisation(amber_data)
        control_mode = self.determine_control_mode(output)
        return output, control_mode

    def determine_current_effective_price(self, output):
        """Determine the current effective price of electricity in $/kWh based on the MPC plan and current conditions. This can be used to control devices through HA based on the current value of electricity."""
        grid_net_list = output["grid_net"] # if grid_net is positive we are importing power 
        feedIn_price_list = output["prices_sell"]
        general_price_list = output["prices_buy"]
        solar_used_list = output["solar_used"]
        solar_forecast_list = output["solar_forecast"]

        for i, grid_net in enumerate(grid_net_list):
            if(grid_net > self.power_threshold): # If there is significant grid import, set price to grid import price
                return general_price_list[i]
            elif(grid_net < -self.power_threshold): # If there is significant grid export, set price to grid export price
                if(feedIn_price_list[0] > feedIn_price_list[i]): # If the current feed in price is higher than the future feed in price, use the current feed in price as the effective price as if power was lower we would be exporting now.
                    return feedIn_price_list[0]
                else:   
                    return feedIn_price_list[i]
            else: # If there is no significant import or export, set price based on solar conditions
                if(solar_used_list[i] < solar_forecast_list[i] - self.power_threshold): # If solar is being curtailed, set price to zero as using more power won't cost anything
                    return 0
                
        return general_price_list[0] # Default to current grid price if no significant import or export is occouring

def approx_equal(a, b, threshold = 0.2):
    return abs(a-b) < threshold

'''
from amber_api import AmberAPI  
from ha_api import HomeAssistantAPI
import ha_mqtt
from energy_controller import EnergyController
import PlantControl
from api_token_secrets import HA_URL, HA_TOKEN, AMBER_API_TOKEN, SITE_ID
from RBC import RBC


amber = AmberAPI(AMBER_API_TOKEN, SITE_ID, errors=True)

plant = PlantControl.Plant(HA_URL, HA_TOKEN, errors=True) 
ha = HomeAssistantAPI(
        base_url=HA_URL,
        token=HA_TOKEN,
        errors=True
    )
EC = EnergyController(
    ha=ha,
    ha_mqtt=ha_mqtt, 
    plant=plant,
)

rbc = RBC(
    ha=ha, 
    ha_mqtt=ha_mqtt,
    plant=plant, 
    EC=EC,
    buffer_percentage_remaining=35, # percentage to inflate predicted load consumption
)

mpc = MPC(ha, plant, EC)

amber_data = amber.get_data(forecast_hrs=mpc.forecast_hrs)

output = mpc.run_optimisation(amber_data)
print(mpc.determine_plan_modes(output))
#mpc.display_results(output)
'''