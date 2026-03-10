#pip install ecos
#pip install cvxpy numpy pandas
import numpy as np
import cvxpy as cp
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import matplotlib.dates as mdates
import time
from energy_controller import ControlMode
from mpc_logger import logger

import json
import paho.mqtt.client as mqtt
import const
import config_manager

mqtt_client = mqtt.Client()
mqtt_client.username_pw_set(config_manager.MQTT_USER, config_manager.MQTT_PASS) 
mqtt_client.connect(const.MQTT_HOST, const.MQTT_PORT)
mqtt_client.loop_start()

class MPC:
    def __init__(self, ha, plant, EC, local_tz, demand_tarrif):
        self.plant = plant
        self.ha = ha
        self.EC = EC
        self.local_tz = local_tz

        self.power_threshold = 0.2 # Threshold when comparing power values

        self.update_limits()    # Update fixed limits (some are required for config)

        # ---------- Config ----------
        self.forecast_hrs = 24
        self.steps_per_price = 30 // 5  # = 6
        self.steps_per_hr = 60 // 5

        self.N_30min = self.forecast_hrs * (60 // 30) # forecast hours, 5-min timesteps
        self.N_5min = self.forecast_hrs * (60 // 5)
        self.amber_forecast_30min_intervals = (60//30)*12    # Get the max 12hr forecast
        self.amber_past_30min_intervals = self.N_30min - self.amber_forecast_30min_intervals  # Fill the rest of the sim with past prices
        self.amber_5min_intervals = (60//5)*12

        self.load_inflation_percentage = 10 # Percentage to inflate the load forecast by to ensure we don't run out in the morning.

        self.dt_5min = 5/60      # 5 minutes in hours

        # Reward and penalty settings
        self.discharge_efficiency = 0.95
        self.battery_min_export_cost = 0.07  # $/kWh (Export will only occour ABOVE this value)
        self.grid_import_penalty_cost = 0.02 # $/kWh penalty for using grid power
        self.full_battery_reward = self.grid_import_penalty_cost + 0.021  # $/kWh — tune this value to encourage the battery to be full by the end of the solar day
        self.maintain_soc_reward = 0 #0.0002 # $/kWh / interval reward for maintaining higher SOC throughout the day
        self.demand_tarrif = demand_tarrif # True if the selected site has a demand tarrif applied
        self.current_effective_price = 0 # Set to zero until we run an optimisation and determine the current effective price based on the MPC plan and current conditions

        # Profit Variables
        self.profit_remaining_today = 0
        self.profit_tomorrow = 0
        
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
        self.historical_data = self.plant.historical_data(hours=6) # Get the last 6 hours of historical data
        self.daily_profit = self.plant.daily_net_profit
        
        # ---------- Forecasts ----------
        # Load Forecast
        load_power_states = self.plant.forecast_load_power(forecast_hours_from_now=self.forecast_hrs) # Calculate the average load power
        self.load_5min = [powerstate.avg_state*(1+self.load_inflation_percentage/100.0) for powerstate in load_power_states]
        
        
        # Solar Forecast
        self.solar_5min = self.plant.forecast_solar_power(forecast_hours_from_now=self.forecast_hrs)

        # Inject the current real load and solar values into the sim
        if(inject_real_values):
            # Inject the avg of the last 5 minutes of solar and load power
            self.solar_5min[0] = (self.solar_5min[0] + self.historical_data["solar_power"][-1]) / 2 # Avgerage the last 5 minutes of solar with the forecast to make a more realistic value for the current timestep
            self.load_5min[0] = self.historical_data["load_power"][-1] # Inject the current real load power value into the sim (change to 5min avg of the most recent 5min interval if possible)


            # Inject the current instantaneous solar and load values into the sim
            #self.solar_5min[0] = self.plant.solar_kw #change to 5min avg of these instantaneous values
            #self.load_5min[0] = self.plant.load_power
        
        if(max(self.load_5min) > self.grid_import_limit or min(self.load_5min)):
            logger.warning(f"Some load values fall outside of limits, Max Load: {max(self.load_5min)}, Min Load: {min(self.load_5min)}. Clipping to ensure solver feasability, please report this if it occours frequently.")

        self.load_5min = [min(max(load, 0.0), self.grid_import_limit)  for load in self.load_5min] # Don't allow negative load or solar or load greater than import limit
        self.solar_5min = [max(solar, 0.0) for solar in self.solar_5min]

        

        # Amber Forecast (forecast hrs is set in main.py in the get_data call)
        self.demand_tarrif_price = amber_data.demand_tarrif_price
        general_price_forecast = amber_data.general_extrapolated_forecast
        feed_in_price_forecast = amber_data.feedIn_extrapolated_forecast
        self.demand_window_forecast = np.array(amber_data.demand_window_extrapolated_forecast, dtype=float)

        # Convert to $/kWh
        self.prices_buy = np.array(general_price_forecast) / 100      # buy price in $ from cents
        self.prices_sell  = np.array(feed_in_price_forecast) / 100      # sell price in $ from cents

        #self.prices_buy[0:5] = 0.03 #Testing
        #self.prices_sell[0:5] = 0.01
        #self.soc_init = 0.95*self.soc_max

    def run_optimisation(self, amber_data):
        self.update_values(amber_data)

        self.prices_sell = self.prices_sell - 0.0001 # Not sure what this is for

        #logger.error("Messing with prices!!")
        #self.prices_sell[180:] = 0.02 # Allow testing of various pricings
        #self.prices_buy[180:] = 0.05 

        #self.prices_sell[10:65] = 0.0 # Allow testing of various pricings
        #self.prices_buy[10:65] = 0.04
        
        #self.soc_init = self.soc_min
        #self.prices_sell[100:120] = 10 # Allow testing of various pricings
        #self.prices_buy[100:120] = 11

        start = time.time()
        # ----------- Variables -----------
        # Battery
        p_charge = cp.Variable(int(self.N_5min), nonneg=True)
        p_discharge = cp.Variable(int(self.N_5min), nonneg=True)
        soc = cp.Variable(int(self.N_5min)+1)

        # Solar
        solar_used = cp.Variable(int(self.N_5min), nonneg=True) # Solar used out of the forecast value (allows for curtailment)
        solar_curtail = cp.Variable(int(self.N_5min), nonneg=True) # Approximate amount of curtailment occouring


        # Grid import/export
        grid_import = cp.Variable(int(self.N_5min), nonneg=True)
        grid_export = cp.Variable(int(self.N_5min), nonneg=True)

        # Peak Demand Charge (if demand tarrif is applied)
        peak_demand = cp.Variable(nonneg=True) # Variable to represent the peak demand in the demand window, used for demand tarrif calculation.

        # Inverter
        inverter_power = cp.Variable(int(self.N_5min), nonneg=False) # Discharge to grid is positive

        # ----------- Constraints -----------
        constraints = []
        constraints += [soc[0] == self.soc_init] # Set the inital soc 
        #constraints += [soc[-1] == min(self.soc_max*0.99, self.soc_init)] # Set the final soc to be close to the starting soc but limit to ensure possibility

        for t in range(int(self.N_5min)):
            # SoC dynamics
            constraints += [soc[t+1] == soc[t] + self.dt_5min * self.discharge_efficiency * p_charge[t] 
                            - self.dt_5min / self.discharge_efficiency * p_discharge[t]]
            # SoC limits
            constraints += [soc[t+1] >= self.soc_min, soc[t+1] <= self.soc_max]

            # Battery Power limits
            constraints += [p_charge[t] <= self.p_max_charge]
            constraints += [p_discharge[t] <= self.p_max_discharge]

            # DC Solar Limits
            constraints += [solar_used[t] <= self.solar_5min[t],    # Solar cannot exceed forecast
                            solar_used[t] <= self.solar_dc_max,     # DC MPPT Limit
                            solar_used[t] + solar_curtail[t] == self.solar_5min[t] # Solar Curtailment
                            ]     
            
            # DC Balance, Sum Inputs == Sum Outputs to DC bus
            constraints += [solar_used[t] + p_discharge[t] == p_charge[t] + inverter_power[t]]

            # AC Power Balance, Sum AC Sources == Sum AC Sinks
            constraints += [grid_import[t] + inverter_power[t] == self.load_5min[t] + grid_export[t]]

            constraints += [grid_import[t] <= self.grid_import_limit,
                            grid_export[t] <= self.grid_export_limit]

            # Inverter AC Limit
            constraints += [inverter_power[t] <= self.inverter_p_max,
                            inverter_power[t] >= -self.inverter_p_max]
            

        # Constrain peak_demand to be >= grid_import at every demand window interval if demand tarrif is applied
        if self.demand_tarrif:
            for t in range(int(self.N_5min)):
                if self.demand_window_forecast[t] > 0:
                    constraints += [peak_demand >= grid_import[t]]


        # Find end of TODAY's solar window (ignore tomorrow's solar)
        # Solar day = first time solar drops to ~0 after having been >0
        solar_started = False
        solar_end_index = 0

        for t in range(int(self.N_5min)):
            if self.solar_5min[t] > self.load_5min[t]:
                solar_started = True
            elif solar_started and self.solar_5min[t] <= self.load_5min[t]:
                solar_end_index = t - 1  # last index with meaningful solar
                break  # stop at first sunset — ignore tomorrow


        # -------------------------------
        # Objective: Minimise cost including battery discharge cost
        # -------------------------------
        
        objective_list = (
            cp.multiply(grid_import, self.prices_buy) * self.dt_5min
            - cp.multiply(grid_export, self.prices_sell) * self.dt_5min
            + cp.multiply(grid_import, self.grid_import_penalty_cost) * self.dt_5min
            + cp.multiply(self.battery_min_export_cost, p_discharge) * self.dt_5min
            - cp.multiply(self.maintain_soc_reward, soc[0:-1]) # Small reward for maintaining higher SOC throughout the day
        )

        non_sum_objective_list = 0

        if solar_started and solar_end_index > 0:
            non_sum_objective_list = non_sum_objective_list - cp.multiply(self.full_battery_reward, soc[solar_end_index]) # Encorage the battery to be full by the end of the solar day

        if(self.demand_tarrif):
            non_sum_objective_list = non_sum_objective_list + peak_demand * self.demand_tarrif_price # no dt multiply - it's a peak charge


        objective = cp.Minimize(
            cp.sum(objective_list)
            + non_sum_objective_list # Don't sum the one off objectives 
        )
        
        # ---------- Solve ----------
        prob = cp.Problem(objective, constraints)
        prob.solve(solver=cp.ECOS)
        logger.info(f"Solver took {round(time.time()-start,2)} seconds to solve")

        # Don't continue if the solver failed
        if prob.status not in ("optimal", "optimal_inaccurate"):
            raise RuntimeError(f"MPC solve failed: {prob.status}")
        
        else: # Sim successfull 
            # ---------- Results ----------
            battery_power = (p_discharge.value - p_charge.value).tolist()
            grid_net = (grid_import.value - grid_export.value).tolist()
            #hours = np.arange(int(self.N_5min)) * self.dt_5min

            now = datetime.now(self.local_tz).replace(second=0, microsecond=0)
            minute = (now.minute // 5) * 5
            now = now.replace(minute=minute)
            time_index = [now + timedelta(minutes=5 * i) for i in range(int(self.N_5min))]
            
            # if solar_started and solar_end_index > 0:
            #     logger.info(f"Solar Day ends at index {solar_end_index} time:{time_index[solar_end_index]}")


            grid_kwh_import_per_interval = grid_import.value / self.steps_per_hr 
            grid_kwh_export_per_interval = grid_export.value / self.steps_per_hr 

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
            battery_soc = [round(x, 2) for x in soc.value.tolist()]
            grid_net = [round(x, 2) for x in grid_net]
            inverter_power = [round(x, 2) for x in inverter_power.value.tolist()]
            solar_forecast_power = [round(x, 2) for x in self.solar_5min]
            solar_used_power = [round(x, 2) for x in solar_used.value.tolist()]
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
                    "peak_demand": float(peak_demand.value),
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
                return feedIn_price_list[i]
            else: # If there is no significant import or export, set price based on solar conditions
                if(solar_used_list[i] < solar_forecast_list[i] - self.power_threshold): # If solar is being curtailed, set price to zero as using more power won't cost anything
                    return 0
                
        return general_price_list[0] # Default to current grid price if no significant import or export is occouring
    
    def display_results(self, output):
        logger.info(f"Profit: ${round(output['profit'], 2)}")
        #print(f"Solar Remaining {np.sum(solar_5min*(5/60))}")
        logger.info(f"solar used: {round(output['solar_used'][0],2)}  bat: {round(output['battery_power'][0],2)}  load: {round(output['load'][0],2)} grid: {round(output['grid_net'][0],2)}  inverter_power: {round(output['inverter_power'][0], 2)}")

        plt.figure(figsize=(14,8))

        time_index = output["time_index"]
        # --------- Top plot: battery & net load ----------
        plt.subplot(2,1,1)
        plt.plot(time_index, output["battery_power"], label='Battery Power (kW)', color='blue')
        plt.plot(time_index, output["load"], label='Load', color='orange', alpha=1)
        plt.plot(time_index, output["solar_forecast"], label='Available Solar', color='limegreen', alpha=1, linestyle='--')
        plt.plot(time_index, output["solar_used"], label='Solar Used', color='limegreen')
        plt.plot(time_index, output["inverter_power"], label='Inverter Power (kW)', color='purple')
        plt.plot(time_index, output["grid_net"], label='Grid Net Import (+ buy, - sell)', color='black', linestyle='--')
        plt.axhline(0, color='black', linewidth=0.5)
        plt.ylabel('Power (kW)')
        plt.title('Battery Schedule & Net Load with 24h Amber Forecast and Discharge Cost')
        plt.legend()
        plt.grid(True)

        # Secondary y-axis for prices
        plt.twinx()
        plt.plot(time_index, output["prices_buy"], label='Buy Price', color='green')
        plt.plot(time_index, output["prices_sell"], label='Sell Price', color='red')
        plt.ylabel('Price ($/kWh)')
        plt.legend(loc='upper right')

        # --------- Bottom plot: SOC ----------
        plt.subplot(2,1,2)
        plt.plot(time_index, output["soc"][0:-1], label='Battery SOC (kWh)', color='purple')
        plt.axhline(self.soc_min, color='red', linestyle='--', label='SOC Min/Max')
        plt.axhline(self.soc_max, color='red', linestyle='--')

        plt.xlabel('Hour of Day')
        plt.ylabel('SOC (kWh)')
        plt.title('Battery State of Charge')
        plt.legend()
        plt.grid(True)

        for ax in plt.gcf().axes:
            ax.xaxis.set_major_locator(mdates.HourLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            ax.tick_params(axis='x', rotation=0)

        plt.tight_layout()
        plt.show()

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