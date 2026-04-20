from dataclasses import dataclass
import datetime
from zoneinfo import ZoneInfo
import time
import numpy as np
import math
import pandas as pd
from collections import defaultdict
from typing import Any
import config_manager
from mpc_logger import logger
from exceptions import HAAPIError, SigenergyConnectionError, PlantControlError
import traceback
from helper_functions import round_minutes


@dataclass
class BinnedStateClass:
    states: list[Any] # States that make up the avg
    avg_state: Any # Avg of the states
    time: datetime # Start time of the bin


class Plant:
    def __init__(self, ha):
        self.ha = ha
        self.local_tz = ha.local_tz
        self.check_for_enabled_entites() # Check to make sure all the required entities are enabled before starting the app to prevent issues later on.

        self.control_mode_options = [
            "Standby",
            "Maximum Self Consumption",
            "Command Charging (PV First)",
            "Command Charging (Grid First)",
            "Command Discharging (PV First)",
            "Command Discharging (ESS First)"]
        self.rated_capacity = self.get_sigenergy_numeric_state(config_manager.battery_rated_capacity_entity_id)
        self.max_discharge_power = self.get_config_entry_value(config_manager.battery_max_discharge_power_limit_entity_id)
        self.max_charge_power = self.get_config_entry_value(config_manager.battery_max_charge_power_limit_entity_id)
        self.max_pv_power = self.get_config_entry_value(config_manager.pv_max_power_limit_entity_id)
        self.max_inverter_power = self.get_config_entry_value(config_manager.inverter_max_power_limit_entity_id)
        self.max_export_power = self.get_config_entry_value(config_manager.export_max_power_limit_entity_id)
        self.max_import_power = self.get_config_entry_value(config_manager.import_max_power_limit_entity_id)

        self.ev_enabled = config_manager.ev_charging_power_entity_id != ""
                            
        self.time_step_minutes = 5
        self.load_avg_days = 3

        self.last_load_data_retrival_timestamp = 0
        self.avg_load_day = None

        self.last_base_load_estimate_timestamp = 0
        self.base_load_estimate = None

        self.history_since_midnight = None

        self.update_data()

        logger.debug(f"Battery Capacity: {self.rated_capacity} kWh | "
                     f"Max Discharge: {self.max_discharge_power} kW | "
                     f"Max Charge: {self.max_charge_power} kW | "
                     f"Max PV: {self.max_pv_power} kW | "
                     f"Max Inverter: {self.max_inverter_power} kW | "
                     f"Max Export: {self.max_export_power} kW | "
                     f"Max Import: {self.max_import_power} kW | "
                     f"Backup Buffer: {self.kwh_backup_buffer} kWh"
                )

    def get_sigenergy_state(self, entity_id):
        state_payload = self.ha.get_state(entity_id)
        if isinstance(state_payload, dict) and state_payload.get("state") == "unavailable":
            raise SigenergyConnectionError(
                f"Sigenergy system is unavailable (entity: '{entity_id}'). "
                "It is likely offline or has a bad connection."
            ) from None
        return state_payload

    def get_sigenergy_numeric_state(self, entity_id):
        state_payload = self.get_sigenergy_state(entity_id)
        state = state_payload.get("state") if isinstance(state_payload, dict) else None
        try:
            return float(state)
        except (TypeError, ValueError):
            raise HAAPIError(
                f"Unable to convert state '{state}' for entity '{entity_id}' to float."
            ) from None
        
    def get_config_entry_value(self, entry_id): # Try to get the value from a config entry that is either a string float or an entity id
        try:
            val = float(entry_id)
            if(val != None and val > 0):
                return val
            else:
                logger.error(f"Value set for {entry_id} : {val} is invailid.")
        except (ValueError, TypeError):
            try:
                # If the config entry id cannot be parsed as a float it should be the entity_id
                val = self.get_sigenergy_numeric_state(entry_id)
                return val  
            except Exception as e:
                logger.error(f"Unable to get entity id or float from config entry '{entry_id}'. Please check the entity id or ensure it is a float. Exception: {e}")

    def get_optional_config_entry_value(self, entry_id, default_value=0.0):
        if(entry_id is None or entry_id == ""):
            return float(default_value)
        try:
            val = self.get_config_entry_value(entry_id)
            if(val is None):
                return float(default_value)
            return float(val)
        except Exception:
            logger.warning(f"Unable to read optional config value '{entry_id}', defaulting to {default_value}.")
            return float(default_value)

    def parse_boolean_state(self, entity_id, default=False):
        if(entity_id is None or entity_id == ""):
            return bool(default)
        state_payload = self.ha.get_state(entity_id)
        if(not isinstance(state_payload, dict)):
            return bool(default)
        state = str(state_payload.get("state", "")).strip().lower()
        true_states = {"on", "true", "home", "connected", "plugged", "plugged_in", "yes"}
        false_states = {"off", "false", "not_home", "disconnected", "unplugged", "no"}
        if(state in true_states):
            return True
        if(state in false_states):
            return False
        try:
            return float(state) > 0
        except (TypeError, ValueError):
            return bool(default)

    def get_plant_mode(self):
        return self.get_sigenergy_state(config_manager.ems_control_mode_entity_id)["state"]

    def update_data(self):
        self.battery_soc = self.get_sigenergy_numeric_state(config_manager.battery_soc_entity_id)
        self.kwh_backup_buffer = (self.get_sigenergy_numeric_state(config_manager.backup_soc_entity_id)/100.0) * self.rated_capacity
        self.kwh_stored_energy = self.get_sigenergy_numeric_state(config_manager.battery_stored_energy_entity_id)
        self.kwh_stored_available = self.kwh_stored_energy - self.kwh_backup_buffer
        self.kwh_charge_unusable = (1-(self.get_sigenergy_numeric_state(config_manager.charge_cutoff_soc_entity_id)/100.0)) * self.rated_capacity # kWh of buffer to 100% IE the charge limit 
        self.kwh_till_full = self.get_sigenergy_numeric_state(config_manager.battery_kwh_till_full_entity_id) - self.kwh_charge_unusable
        self.battery_kw = self.get_sigenergy_numeric_state(config_manager.battery_power_entity_id)
        if(config_manager.battery_power_sign_convention == "+ Charge, - Discharge"): # If battery power is the wrong way around, flip it
            self.battery_kw = -self.battery_kw
        # Internal battery power convention ^^^^^^^:
        #   +kW = discharging (battery supplying power)
        #   -kW = charging (battery absorbing power)

        self.solar_kw = self.get_sigenergy_numeric_state(config_manager.solar_power_entity_id)
        self.solar_kwh_today = self.get_sigenergy_numeric_state(config_manager.plant_solar_kwh_today_entity_id)
        self.solar_kw_remaining_today = self.get_sigenergy_numeric_state(config_manager.solcast_solar_kwh_remaining_today_entity_id)
        self.inverter_power = self.get_sigenergy_numeric_state(config_manager.inverter_power_entity_id)
        self.grid_power = self.get_sigenergy_numeric_state(config_manager.grid_power_entity_id)
        self.load_power = self.get_sigenergy_numeric_state(config_manager.load_power_entity_id)
        self.avg_daily_load = sum(bin.avg_state*(self.time_step_minutes/60) for bin in self.get_load_avg(days_ago=self.load_avg_days))
        
        self.ev_plugged_in = self.parse_boolean_state(config_manager.ev_plugged_in_entity_id, default=False)
        self.ev_power_kw = 0.0
        if(self.ev_enabled):
            self.ev_power_kw = max(0.0, self.get_sigenergy_numeric_state(config_manager.ev_charging_power_entity_id))
        self.base_load_power = max(self.load_power - self.ev_power_kw, 0.0)
        self.ev_soc = None
        if(config_manager.ev_soc_entity_id != ""):
            self.ev_soc = min(max(self.get_sigenergy_numeric_state(config_manager.ev_soc_entity_id), 0.0), 100.0)
        self.ev_battery_capacity_kwh = self.get_optional_config_entry_value(config_manager.ev_battery_capacity_kwh, default_value=0.0)
        self.ev_max_charge_power = self.get_optional_config_entry_value(config_manager.ev_max_charge_power_entity_id, default_value=0.0)
        self.ev_min_charge_power = max(self.get_optional_config_entry_value(config_manager.ev_min_charge_power_kw, default_value=0.0), 0.0)

        self.calculate_today_profit_cost()
        
        self.hours_till_full = 0
        self.hours_till_empty = 0
        if(self.battery_kw < 0):
            self.hours_till_full = round(self.kwh_till_full / abs(self.battery_kw), 2)
        elif(self.battery_kw > 0):
            self.hours_till_empty = round(self.kwh_stored_available / abs(self.battery_kw), 2)
        
    def system_curtailing(self, derate_allowance_kw=1.0, tolerance_kw=0.1):
        """
        Return curtailment status and reason based on active limits.

        Battery SOC >= 97% is treated as a charging constraint because near-full
        batteries commonly trigger charge tapering/curtailment behaviour.
        """
        if(self.get_sigenergy_state(config_manager.ha_ems_control_switch_entity_id)['state'] != "on"):
            return {
                "curtailing": False,
                "reason": "Remote EMS Switch Off, unable to determine curtailment status",
            }

        control_mode = self.get_plant_mode()

        inverter_limit_kw = self.get_sigenergy_numeric_state(config_manager.inverter_max_power_limit_entity_id)
        charge_limit_kw = self.get_sigenergy_numeric_state(config_manager.battery_charge_limiter_entity_id)
        pv_limit_kw = self.get_sigenergy_numeric_state(config_manager.pv_limiter_entity_id)
        export_limit_kw = self.get_sigenergy_numeric_state(config_manager.export_limiter_entity_id)

        charge_disabled_modes = {
            "Standby",
            "Command Discharging (PV First)",
            "Command Discharging (ESS First)",
        }
        high_soc_curtailment = self.battery_soc >= 97
        charging_disabled = control_mode in charge_disabled_modes or high_soc_curtailment
        effective_charge_limit_kw = 0 if charging_disabled else max(charge_limit_kw, 0)

        ac_sink_limit_kw = max(self.load_power, 0) + max(export_limit_kw, 0)
        configured_inverter_headroom_kw = min(max(inverter_limit_kw, 0), ac_sink_limit_kw)
        derated_inverter_headroom_kw = min(max(inverter_limit_kw - derate_allowance_kw, 0), ac_sink_limit_kw)

        configured_ceiling_kw = min(max(pv_limit_kw, 0), configured_inverter_headroom_kw + effective_charge_limit_kw)
        derated_ceiling_kw = min(max(pv_limit_kw, 0), derated_inverter_headroom_kw + effective_charge_limit_kw)

        curtailing_configured = self.solar_kw >= configured_ceiling_kw - tolerance_kw
        curtailing_derated = self.solar_kw >= derated_ceiling_kw - tolerance_kw
        curtailing = curtailing_configured or curtailing_derated

        limiting_components = {
            "pv_limit": pv_limit_kw,
            "derated_inverter_limit": derated_inverter_headroom_kw + effective_charge_limit_kw,
            "ac_sink_limit": ac_sink_limit_kw + effective_charge_limit_kw,
        }
        limiting_reason = min(limiting_components, key=limiting_components.get)

        reason_text_map = {
            "pv_limit": f"PV limit ({round(pv_limit_kw, 2)} kW)",
            "derated_inverter_limit": f"Inverter + Charge Limit ({round(derated_inverter_headroom_kw + effective_charge_limit_kw, 2)} kW)",
            "ac_sink_limit": f"Load + export sink limit ({round(ac_sink_limit_kw + effective_charge_limit_kw, 2)} kW)",
        }

        reason = reason_text_map[limiting_reason]
        '''
        if control_mode in charge_disabled_modes:
            reason_parts.append("battery charging disabled by mode")
        if high_soc_curtailment:
            reason_parts.append(f"battery SOC high ({round(self.battery_soc, 1)}%)")'''

        return {
            "curtailing": curtailing,
            "reason": reason,
        }
    
    def historical_data(self, start_datetime=None, end_datetime=None, hours=None, bin_period=5): # Get the requested hours of historical data for the plant being (SOC, battery power, inverter power, solar power, grid power, load power and prices.) in order oldest to newest
        """
        hours  -> hours of historical data to retreive
        bin_period -> bin size in minutes to average data across

        Returns:
            List of BinnedStateClass objs from oldest to newest (-1 index will be the most recent data):
            [
                bin.time": bin_start_datetime,
                bin.avg_state": average_value_in_bin
                ...
            ]
        """
        start_timestamp = time.time()
        if(hours == None and (start_datetime == None or end_datetime == None)):
            logger.error("Error: Must provide either hours or start and end datetimes for historical data retrieval.")
            raise ValueError(f"Must provide either hours or start and end datetimes for historical data retrieval. Received hours: {hours}, start_datetime: {start_datetime}, end_datetime: {end_datetime}")

        if(hours != None and (start_datetime != None or end_datetime != None)):
            logger.error("Error: Must provide either hours or start and end datetimes for historical data retrieval, not both.")
            raise ValueError(f"Must provide either hours or start and end datetimes for historical data retrieval, not both. Received hours: {hours}, start_datetime: {start_datetime}, end_datetime: {end_datetime}")
        
        if(hours != None):
            now = datetime.datetime.now(self.local_tz)
            rounded_now = round_minutes(time=now, nearest_minute=bin_period)
            start_datetime = round_minutes(time=rounded_now - datetime.timedelta(hours=hours), nearest_minute=bin_period)
            end_datetime = rounded_now

        requested_hours = (end_datetime - start_datetime).total_seconds() / 3600
        logger.debug(f"Requesting historical data from {start_datetime.isoformat()} to {end_datetime.isoformat()} ({round(requested_hours, 2)} hours)")

        battery_soc_state_history = self.ha.get_history(config_manager.battery_soc_entity_id, start_time=start_datetime, end_time=end_datetime)
        battery_power_state_history = self.ha.get_history(config_manager.battery_power_entity_id, start_time=start_datetime, end_time=end_datetime)
        if(config_manager.battery_power_sign_convention == "+ Charge, - Discharge"):
            for state in battery_power_state_history:
                try:
                    state.state = -float(state.state)
                except:
                    pass
        # Internal battery power convention ^^^^^^^:
        #   +kW = discharging (battery supplying power)
        #   -kW = charging (battery absorbing power)

        inverter_power_state_history = self.ha.get_history(config_manager.inverter_power_entity_id, start_time=start_datetime, end_time=end_datetime)
        solar_power_state_history = self.ha.get_history(config_manager.solar_power_entity_id, start_time=start_datetime, end_time=end_datetime)
        load_power_state_history = self.ha.get_history(config_manager.load_power_entity_id, start_time=start_datetime, end_time=end_datetime)
        ev_power_state_history = []
        if(self.ev_enabled):
            ev_power_state_history = self.ha.get_history(config_manager.ev_charging_power_entity_id, start_time=start_datetime, end_time=end_datetime)
        
        grid_power_state_history = self.ha.get_history(config_manager.grid_power_entity_id, start_time=start_datetime, end_time=end_datetime)
        grid_import_kwh_state_history = self.ha.get_history(config_manager.plant_daily_import_kwh_entity_id, start_time=start_datetime, end_time=end_datetime)
        grid_export_kwh_state_history = self.ha.get_history(config_manager.plant_daily_export_kwh_entity_id, start_time=start_datetime, end_time=end_datetime)

        feed_in_state_history = self.ha.get_history("sensor.mpc_energy_manager_device_feed_in_price", start_time=start_datetime, end_time=end_datetime) 
        general_price_state_history = self.ha.get_history("sensor.mpc_energy_manager_device_general_price", start_time=start_datetime, end_time=end_datetime)
        working_mode_state_history = self.ha.get_history("sensor.mpc_energy_manager_device_working_mode", start_time=start_datetime, end_time=end_datetime, type=str)

        #requested_data_received = self.validate_returned_data_timedelta(inverter_power_state_history, start_datetime, end_datetime)


        binned_battery_soc_state_history = self.bin_data(battery_soc_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime)
        binned_battery_power_state_history = self.bin_data(battery_power_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime)
        binned_inverter_power_state_history = self.bin_data(inverter_power_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime)
        binned_load_power_state_history = self.bin_data(load_power_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime)

        binned_ev_power_state_history = []
        if(len(ev_power_state_history) > 0):
            try:
                binned_ev_power_state_history = self.bin_data(ev_power_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime)
            except Exception as e:
                logger.warning(f"Unable to bin EV power history, defaulting EV history to 0 kW for this window. Exception: {e}")
        if(len(binned_ev_power_state_history) == 0):
            binned_ev_power_state_history = [BinnedStateClass(states=[], avg_state=0.0, time=state.time) for state in binned_load_power_state_history]
        
        binned_solar_power_state_history = self.bin_data(solar_power_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime)
        binned_grid_power_state_history = self.bin_data(grid_power_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime)

        binned_grid_import_kwh_state_history = self.bin_data(grid_import_kwh_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime)
        binned_grid_export_kwh_state_history = self.bin_data(grid_export_kwh_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime)

        
        binned_feed_in_state_history = self.bin_data(feed_in_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime, interpolation_method="step")
        binned_general_price_state_history = self.bin_data(general_price_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime, interpolation_method="step")# Step Interpolation as prices dont gradually change
        binned_working_mode_state_history = self.bin_data(working_mode_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime, string_state=True)

        binned_battery_soc_kwh_history = [(item.avg_state / 100.0) * self.rated_capacity for item in binned_battery_soc_state_history]
        
        history_time_index = [item.time.isoformat() for item in binned_battery_soc_state_history] # Get the time marks from the data

        logger.debug(f"Received data bins span from {history_time_index[0]} to {history_time_index[-1]} ({len(history_time_index)} bins), request took {round(time.time()-start_timestamp,2)} seconds to retrieve and process.")

        output = {
            "time_index": history_time_index,
            "soc": binned_battery_soc_kwh_history,
            "battery_power": [state.avg_state for state in binned_battery_power_state_history],
            "inverter_power": [state.avg_state for state in binned_inverter_power_state_history],
            "solar_power": [state.avg_state for state in binned_solar_power_state_history],
            "load_power": [state.avg_state for state in binned_load_power_state_history],
            "ev_power": [max(0.0, state.avg_state) for state in binned_ev_power_state_history],
            "grid_power": [state.avg_state for state in binned_grid_power_state_history],
            "prices_sell": [state.avg_state/100.0 for state in binned_feed_in_state_history], # Converted to dollars from cents
            "prices_buy": [state.avg_state/100.0 for state in binned_general_price_state_history],
            "plan_modes": [state.avg_state for state in binned_working_mode_state_history],
            "grid_import_kwh": [state.avg_state for state in binned_grid_import_kwh_state_history],
            "grid_export_kwh": [state.avg_state for state in binned_grid_export_kwh_state_history],
        }
        return output
    
    def get_profit_history(self): #Get the history required for the profit calcs and use cached data if its not too old to avoid the expensive historical data retrieval and processing if possible.
        now = datetime.datetime.now(self.local_tz)
        rounded_now = round_minutes(time=now, nearest_minute=self.time_step_minutes)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if self.history_since_midnight is not None and self.history_since_midnight.get("time_index"):
            first_cached_timestamp = self.history_since_midnight["time_index"][0]
            first_cached_dt = datetime.datetime.fromisoformat(first_cached_timestamp)
            # Reset the cache at local midnight so "today" calculations do not include yesterday's bins.
            if first_cached_dt.date() != now.date():
                self.history_since_midnight = None

        if self.history_since_midnight == None:
            self.history_since_midnight = self.historical_data(start_datetime=today_start, end_datetime=rounded_now, bin_period=self.time_step_minutes)
            return self.history_since_midnight
        else:
            last_history_timestamp = self.history_since_midnight['time_index'][-1]
            start = datetime.datetime.fromisoformat(last_history_timestamp)
            end = now
            minutes_since_last_history = (end - start).total_seconds() / 60
            if minutes_since_last_history > self.time_step_minutes: # If the history is more than 5 minutes old, get new history
                latest_history = self.historical_data(start_datetime=start, end_datetime=rounded_now, bin_period=self.time_step_minutes)
                logger.debug(f"Updating profit history cache with {len(latest_history['time_index'])} new data points spanning from {latest_history['time_index'][0]} to {latest_history['time_index'][-1]}.")

                last_ts = self.history_since_midnight["time_index"][-1]
                new_times = latest_history["time_index"]

                if new_times and new_times[0] == last_ts:
                    # Override the last cached point with latest recomputed point
                    for k in self.history_since_midnight.keys():
                        self.history_since_midnight[k][-1] = latest_history[k][0]
                    start_idx = 1
                else:
                    # No exact overlap found at first point; append from first strictly newer point
                    start_idx = 0
                    while start_idx < len(new_times) and new_times[start_idx] <= last_ts:
                        start_idx += 1

                # Append remaining new points
                for k in self.history_since_midnight.keys():
                    self.history_since_midnight[k].extend(latest_history[k][start_idx:])

        return self.history_since_midnight

    def calculate_today_profit_cost(self):
        # Get today's historical data
        history = self.get_profit_history()

        now = datetime.datetime.now(self.local_tz)

        # Check to see if the requested amount of data was recieved, use the configured default if not
        if(len(history['prices_sell']) < 2):
            if(now.time() > datetime.time(0,30)): # If its early in the day, its likely there just isn't enough history yet, so don't log a warning and set profit to 0
                logger.error(f"Insufficent data to calulate profit.")
            self.daily_export_profit = 0
            self.daily_import_cost = 0
            self.daily_net_profit = 0
            return

        # Convert lists to numpy arrays
        export_cumsum = np.array(history["grid_export_kwh"])
        import_cumsum = np.array(history["grid_import_kwh"])
        prices_sell = np.array(history["prices_sell"])
        prices_buy = np.array(history["prices_buy"])

        # Compute per-bin kWh by taking the difference between consecutive cumulative readings
        export_kwh_bin = np.diff(export_cumsum, prepend=export_cumsum[0])  # prepend first element so first bin is correct
        import_kwh_bin = np.diff(import_cumsum, prepend=import_cumsum[0])

        export_kwh_bin = np.where(export_kwh_bin < 0, 0, export_kwh_bin) # Remove negative values (import and export should only increment positivley)
        import_kwh_bin = np.where(import_kwh_bin < 0, 0, import_kwh_bin)

        # Element-wise multiply by corresponding prices
        profit_per_bin = export_kwh_bin * prices_sell
        cost_per_bin = import_kwh_bin * prices_buy

        # Sum up total profit, total cost, net profit
        self.daily_export_profit = np.sum(profit_per_bin)
        self.daily_import_cost = np.sum(cost_per_bin)
        self.daily_net_profit = self.daily_export_profit - self.daily_import_cost

    def check_control_limits(self, working_mode, control_mode, discharge, charge, pv, grid_export, grid_import): # Check if control limits match desired values and change them if required. 
        self.ensure_remote_ems() # Make sure the EMS is able to be controlled

        current_control_mode = self.get_plant_mode()
        curent_discharge_limit = self.get_sigenergy_numeric_state(config_manager.battery_discharge_limiter_entity_id)
        curent_charge_limit = self.get_sigenergy_numeric_state(config_manager.battery_charge_limiter_entity_id)
        curent_pv_limit = self.get_sigenergy_numeric_state(config_manager.pv_limiter_entity_id)
        curent_export_limit = self.get_sigenergy_numeric_state(config_manager.export_limiter_entity_id)
        curent_import_limit = self.get_sigenergy_numeric_state(config_manager.import_limiter_entity_id)

        a = current_control_mode != control_mode or curent_discharge_limit != discharge or curent_charge_limit != charge
        b = curent_pv_limit != pv or curent_export_limit != grid_export or curent_import_limit != grid_import

        wrong_control_mode = current_control_mode != control_mode
        wrong_discharge_limit = curent_discharge_limit != discharge
        wrong_charge_limit = curent_charge_limit != charge
        wrong_pv_limit = curent_pv_limit != pv
        wrong_export_limit = curent_export_limit != grid_export
        wrong_import_limit = curent_import_limit != grid_import

        any_limits_wrong = wrong_control_mode or wrong_discharge_limit or wrong_charge_limit or wrong_pv_limit or wrong_export_limit or wrong_import_limit

        if any_limits_wrong:          
            self.set_control_limits(control_mode, discharge, charge, pv, grid_export, grid_import)
            logger.info(f"Changing control entities for mode: {working_mode}")
            time.sleep(5) # Allow time for HA to update
    
    def ensure_remote_ems(self): # Ensures the remote EMS switch is on provided the automatic control switch is on
        if(self.get_sigenergy_state(config_manager.ha_ems_control_switch_entity_id)['state'] != "on"):
                logger.warning(f"Remote EMS switch is '{self.get_sigenergy_state(config_manager.ha_ems_control_switch_entity_id)['state']}', turning on to allow control.")
                self.ha.set_switch_state(config_manager.ha_ems_control_switch_entity_id, True)
                time.sleep(10) # delay to ensure the change has time to become effective

    def check_for_enabled_entites(self): # Checks to make sure all the entities needed for control are available and enabled, if not it raises an error
        entity_ids = [
            config_manager.ha_ems_control_switch_entity_id,
            config_manager.backup_soc_entity_id,
            config_manager.charge_cutoff_soc_entity_id,
            config_manager.battery_max_discharge_power_limit_entity_id,
            config_manager.battery_max_charge_power_limit_entity_id,
            config_manager.battery_rated_capacity_entity_id,
            config_manager.inverter_max_power_limit_entity_id,
            config_manager.battery_kwh_till_full_entity_id,
            config_manager.battery_stored_energy_entity_id,
            config_manager.battery_max_charge_power_limit_entity_id,
            config_manager.battery_max_discharge_power_limit_entity_id
        ]

        # Only check for the EMS control mode if the HA EMS Control switch is on as otherwise the mode controller is disabled.
        if(self.get_sigenergy_state(config_manager.ha_ems_control_switch_entity_id)['state'] == "on"):
            entity_ids.append(config_manager.ems_control_mode_entity_id)

        unavailable_ids = []
        for entity_id in entity_ids:
            try:
                self.get_sigenergy_state(entity_id)
            except:
                unavailable_ids.append(f"{entity_id}\n")

        numeric_ids = [
            config_manager.pv_max_power_limit_entity_id,
            config_manager.import_max_power_limit_entity_id,
            config_manager.export_max_power_limit_entity_id
        ]
        for config_value in numeric_ids:
            try:
                config_value_float = float(config_value)
            except:
                unavailable_ids.append(f"{entity_id}\n")
        if(len(unavailable_ids) > 0):
            logger.error(f"The required entities are not enabled or don't exist. Please check they are enabled and spelt correctly:")
            for id in unavailable_ids:
                logger.error(id)
            exit()

    def set_control_limits(self, control_mode, discharge, charge, pv, grid_export, grid_import): # Set the control limits to the desired values
        self.ensure_remote_ems() # Make sure the EMS is able to be controlled

        self.ha.set_number(config_manager.battery_discharge_limiter_entity_id, discharge)
        self.ha.set_number(config_manager.battery_charge_limiter_entity_id, charge)
        self.ha.set_number(config_manager.pv_limiter_entity_id, pv)
        self.ha.set_number(config_manager.export_limiter_entity_id, grid_export)
        self.ha.set_number(config_manager.import_limiter_entity_id, grid_import)
        
        if(control_mode in self.control_mode_options):
            self.ha.set_select(config_manager.ems_control_mode_entity_id, control_mode)
        else:
            raise(f"Requested control mode '{control_mode}' is not a valid control mode!")
        
    def interpolate_values(self, values, method="linear"):
        '''takes a list of numeric values with possible None values to interpolate and interpolates the None values using the specified method. Returns a list of the same length with no None values.'''
        s = pd.Series(values)

        if method == "linear":
            # 5, None, None, None, 6 → 5, 5.25, 5.5, 5.75, 6
            return (
                s.interpolate(method="linear")
                .bfill()
                .ffill()
                .tolist()
            )

        elif method == "step":
            # 5, None, None, None, 6 → 5, 5, 5, 5, 6
            return (
                s.ffill()   # forward fill
                .bfill()   # in case the first values are None
                .tolist()
            )

        else:
            raise ValueError("method must be 'linear' or 'step'")

    def bin_data(self, history, bin_period, start_bin_datetime, end_bin_datetime, string_state=False, interpolation_method="linear"): 
        """
        Takes a list of historical state data and bins it into specified time intervals, averaging the state values within each bin. Handles both numeric and string states. Also fills in missing bins with None values and can interpolate those values if desired.

        history[x].state    -> numeric value (string or float)
        history[x].time     -> datetime object (tz-aware)
        start_bin_datetime  -> datetime object for bin start time
        end_bin_datetime    -> datetime object for bin end time
        bin_period          -> time period (minutes) to bin data into

        Returns:
            List of BinnedStateClass objs:
            [
                bin.time": bin_start_datetime,
                bin.avg_state": average_value_in_bin
                ...
            ]
        """
        bin_delta = datetime.timedelta(minutes=bin_period)
        if end_bin_datetime < start_bin_datetime:
            raise ValueError(f"end_bin_datetime: '{end_bin_datetime}' must be greater than or equal to start_bin_datetime: '{start_bin_datetime}'")
        bin_qty = int(((end_bin_datetime - start_bin_datetime).total_seconds()) // bin_delta.total_seconds()) + 1

        # Remove any invalid states from the history list (Unavailable, None, etc)
        clean_history = []
        for hist in history:
            try:
                if hist.state is not None:
                    if not string_state:
                        hist.state = float(hist.state)
                    clean_history.append(hist)
            except (ValueError, TypeError):
                pass  # drop unknown/unavailable/etc
                

        binned_history = []
        current_bin_datetime = start_bin_datetime

        # Build the binned history skeleton with empty states and correct time bins
        for i in range(bin_qty):
            binned_history.append(BinnedStateClass(avg_state=None, states=[], time=current_bin_datetime))
            current_bin_datetime = current_bin_datetime + bin_delta
        
        i = 0 # Incrementer for binned_history
        for state in clean_history:
            delta = state.time - start_bin_datetime # Time delta between start bin time and current state time
            bin_index = int(delta.total_seconds() // bin_delta.total_seconds())
            #print(f"Delta{delta}  idx:{bin_index} binqty:{bin_qty}")

            if 0 <= bin_index < bin_qty:
                binned_history[bin_index].states.append(state.state)

        #for interval in binned_history: # Print for debuging
        #    print(interval.states)

        if not string_state: # If the state is a string, don't try an average it
            for interval in binned_history:
                if(len(interval.states) == 0):
                    interval.avg_state = None
                    #raise Exception(f"Failed to get state data for {interval.time} time period")
                else:
                    interval.avg_state = round(sum(interval.states) / len(interval.states), 2)
            
            # Interpolation
            values = [b.avg_state for b in binned_history]
            values = self.interpolate_values(values, method=interpolation_method)  
            for i, interval in enumerate(binned_history):
                interval.avg_state = round(values[i], 2)

        else: # If the state is a string
            last_known_state = "Unknown"
            if(binned_history[0].states):
                last_known_state = binned_history[0].states[-1]

            for bin in binned_history:
                if(bin.states):
                    bin.avg_state = bin.states[-1]
                    last_known_state = bin.states[-1]
                else:
                    bin.avg_state = last_known_state # If there is no state update in the binned time, the state mustn't have changed so use the last known value

            #print(f"avg: {interval.state} states: {interval.states}")

        #for i in range(len(avg_day)): # Print average for each day and each time
        #    print(avg_day[i].state)
        #    print(avg_day[i].states)       

        return binned_history
    
    def validate_returned_data_timedelta(self, data, requested_start, requested_end, tollerance_minutes=30):
        '''
        data -> array containing datetime objs (data[i].time) for each datapoint
        returns True if the requested amount of data was returned.
        '''
        if(not data):
            logger.error(f"No data returned from the api for the requested times: Start: {requested_start}, End: {requested_end}")
            return False
        else:
            first_time = data[0].time
            last_time = data[-1].time

            # Determine if less data time span was returned than requested
            expected_span = requested_end - requested_start
            actual_span = last_time - first_time 

            # If 30 mintues less data than expected was returned, use the estimated load energy configured.
            if actual_span < expected_span - datetime.timedelta(minutes=tollerance_minutes):
                expected_hours = expected_span.total_seconds() / 3600.0
                actual_hours = max(actual_span.total_seconds(), 0.0) / 3600.0
                logger.warning(
                    f"Requested {round(expected_hours, 1)} hours of history but received "
                    f"{round(actual_hours, 1)} hours."
                )
                return False
        return True
    
    def get_ev_binned_history(self, start, end, time_bucket_size=5):
        '''Gets the EV charging power history, bins it into time buckets.'''
        ev_power_history = self.ha.get_history(config_manager.ev_charging_power_entity_id, start_time=start, end_time=end)

        time_bucket_hours = time_bucket_size / 60.0

        # EV history is allowed to be partial; missing bins are treated as 0 kW EV charging
        # so recently-enabled EV sensors can still contribute without forcing full fallback.
        ev_coverage_ratio = 0.0
        ev_has_data = len(ev_power_history) > 0
        if(ev_has_data):
            requested_seconds = max((end - start).total_seconds(), 1.0)
            ev_span_seconds = max((ev_power_history[-1].time - ev_power_history[0].time).total_seconds(), 0.0)
            ev_coverage_ratio = ev_span_seconds / requested_seconds

        ev_min_coverage_ratio = 0.5

        if(ev_has_data and ev_coverage_ratio >= ev_min_coverage_ratio):
            binned_ev_power = self.bin_data(ev_power_history, bin_period=time_bucket_size, start_bin_datetime=start, end_bin_datetime=end, interpolation_method="step")

            # Avoid interpolation artifacts when EV history is partial by forcing no-data bins to 0 kW.
            for ev_state in binned_ev_power:
                if(len(ev_state.states) == 0):
                    ev_state.avg_state = 0.0
                else:
                    ev_state.avg_state = max(ev_state.avg_state, 0.0)

            if(ev_coverage_ratio < 0.99):
                logger.warning(
                    f"EV power history is partial ({round(ev_coverage_ratio*100.0, 1)}% coverage). "
                    "Using available EV history and assuming 0 kW when unavailable."
                )

            logger.debug("Using EV-debiased load profile for load forecast generation.")
            return binned_ev_power
        else:
            logger.warning("EV power history coverage is insufficient for EV-debiased load forecasting. ")
            return None

    def update_load_avg(self, days_ago=7):
        '''
        Calculate the average load power profile for a day based on the past load history.
        '''

        # Determine the start and end datetimes for the requested history based on the number of days ago to look back from
        today = datetime.datetime.now(self.local_tz).date()
        end_date = today - datetime.timedelta(days=1)
        start_date = end_date - datetime.timedelta(days=days_ago)

        start = datetime.datetime.combine(start_date, datetime.time.min, tzinfo=self.local_tz)
        end = datetime.datetime.combine(end_date, datetime.time.min, tzinfo=self.local_tz)

        load_power_history = self.ha.get_history(config_manager.load_power_entity_id, start_time=start, end_time=end)

        ev_by_day = None
        if(self.ev_enabled):
            ev_binned_history = self.get_ev_binned_history(start, end, self.time_step_minutes)
            ev_by_day = {}
            if ev_binned_history is not None:
                    if ev_binned_history is not None:
                        logger.debug(
                            f"EV history available for load debiasing with {len(ev_binned_history)} bins "
                            f"spanning from {ev_binned_history[0].time} to {ev_binned_history[-1].time}, "
                        )

                        # Split EV load history into days
                        ev_by_day = defaultdict(list)
                        for ev in ev_binned_history:
                            ev_by_day[ev.time.date()].append(ev)
                    
                        logger.debug(f"EV History:{[bin.avg_state for bin in ev_binned_history]}")
            
                
        # Check to see if the requested amount of data was recieved, use the configured default if not
        if(not self.validate_returned_data_timedelta(data=load_power_history, requested_start=start, requested_end=end)):
            configured_avg_load = config_manager.estimated_daily_load_energy_consumption 
            logger.warning(f"Using default load energy of {configured_avg_load} kWh per day.")

            # Create a linearly spaced array climbing from 0 to the total load over a day
            avg_day = []
            for i in range(int(24 * 60 / self.time_step_minutes)):
                t = (datetime.datetime.min + datetime.timedelta(minutes=i * self.time_step_minutes)).time()
                val = (i / (24 * 60 / self.time_step_minutes)) * configured_avg_load
                avg_day.append(BinnedStateClass(avg_state=round(val, 2), states=[], time=t))

            return avg_day # Return the avg day with the default load profile
        

        # If we've got here we must have the requested number of days of load data     

        # Remove any invalid states from the history list (Unavailable, None, etc)
        clean_history = []
        for hist in load_power_history:
            try:
                if hist.state is not None:
                    hist.state = float(hist.state)
                    clean_history.append(hist)
            except (ValueError, TypeError):
                pass  # drop unknown/unavailable/etc
        
        # --- Split history into days ---
        history_by_day = defaultdict(list)
        for h in clean_history:
            history_by_day[h.time.date()].append(h)

        
        # --- Bin history data by day and subtract EV power--- 
        per_day_binned = []
        for day, day_data in history_by_day.items():
            day_start = datetime.datetime.combine(day, datetime.time.min, tzinfo=self.local_tz)
            day_end = datetime.datetime.combine(day, datetime.time.max, tzinfo=self.local_tz)

            try:
                binned = self.bin_data(
                    day_data,
                    bin_period=self.time_step_minutes,
                    start_bin_datetime=day_start,
                    end_bin_datetime=day_end
                )

                 # --- subtract EV per bin ---
                if self.ev_enabled:
                    if ev_by_day is not None:
                        ev_day_bins = ev_by_day.get(day, [])

                        for i in range(min(len(binned), len(ev_day_bins))):
                            ev_kw = ev_day_bins[i].avg_state or 0.0
                            #logger.debug(f"Day {day} Bin {binned[i].time}: Load {binned[i].avg_state} kW - EV {ev_day_bins[i].avg_state} kW = {binned[i].avg_state - ev_kw} kW")
                            binned[i].avg_state = max(binned[i].avg_state - ev_kw, 0.0)
                               
                    else:
                        logger.debug("EV history is unavailable, skipping EV-debiasing for load forecast generation.")

                per_day_binned.append(binned)
            except Exception as e:
                logger.warning(f"Skipping day {day} due to binning error: {e}")

        if not per_day_binned:
            raise PlantControlError("No valid daily data after binning.")
        

        # --- Build average day ---
        num_bins = len(per_day_binned[0])
        avg_day = []

        for i in range(num_bins):
            states = []

            for day_bins in per_day_binned:
                val = day_bins[i].avg_state
                if val is not None and not math.isnan(val):
                    states.append(val)

            if states:
                avg_val = round(sum(states) / len(states), 2)
                avg_val = max(avg_val, 0.0) # Ensure no negative values

            else:
                raise PlantControlError(f"No valid data for time bin {per_day_binned[0][i].time.time()} across all days.")

            avg_day.append(
                BinnedStateClass(
                    avg_state=avg_val,
                    states=states,
                    time=per_day_binned[0][i].time.time()
                )
            )
        
        return avg_day

    def round_forecast_times(self, forecast_hours_from_now=None, forecast_till_time=None, forecast_start_time=None, forecast_end_time=None):
        if forecast_start_time is not None and forecast_end_time is not None:
            rounded_current_time = round_minutes(forecast_start_time, nearest_minute=self.time_step_minutes)
            rounded_forecast_time = round_minutes(forecast_end_time, nearest_minute=self.time_step_minutes)
            return [rounded_current_time, rounded_forecast_time]
        
        rounded_current_time = round_minutes(datetime.datetime.now(self.local_tz), nearest_minute=self.time_step_minutes)
        if(forecast_hours_from_now):
            rounded_forecast_time = round_minutes(rounded_current_time + datetime.timedelta(hours=forecast_hours_from_now), nearest_minute=self.time_step_minutes)
        elif(forecast_till_time):
            rounded_forecast_time = datetime.datetime.combine(rounded_current_time.date(), forecast_till_time, tzinfo=self.local_tz)
            rounded_forecast_time = round_minutes(rounded_forecast_time, nearest_minute=self.time_step_minutes)
            if(rounded_forecast_time <= rounded_current_time):
                rounded_forecast_time = rounded_forecast_time + datetime.timedelta(days=1)
        else:
            raise Exception("Must provide forecast hours or time to determine forecast!")
        
        return [rounded_current_time, rounded_forecast_time]
    
    def get_load_avg(self, days_ago, hours_update_interval=24): # hours_update_interval: frequency to update the load date
        if(time.time() - self.last_load_data_retrival_timestamp > hours_update_interval*60*60 or self.avg_load_day == None):
            self.avg_load_day = self.update_load_avg(days_ago)
            self.last_load_data_retrival_timestamp = time.time()
        return self.avg_load_day
    
    def forecast_load_power(self, forecast_hours_from_now=None, forecast_till_time=None, forecast_start_time=None, forecast_end_time=None):
        avg_day = self.get_load_avg(days_ago=self.load_avg_days)

        # Determine the current and the end of the forecast datetimes, both rounded to 5 min
        [rounded_current_time, rounded_forecast_time] = self.round_forecast_times(
            forecast_hours_from_now,
            forecast_till_time,
            forecast_start_time=forecast_start_time,
            forecast_end_time=forecast_end_time,
        )

        # Create a lookup dict for each time bin: time-of-day → kWh per bin
        avg_day_kw_lookup = {bin.time: bin.avg_state for bin in avg_day}

        forecast_power = []
        forecast_steps = int((rounded_forecast_time - rounded_current_time).total_seconds() // (self.time_step_minutes * 60))

        avg_kw_per_bin = sum(b.avg_state for b in avg_day) / len(avg_day) # Used below to fallback if no data for specific bin

        for i in range(forecast_steps):
            point_time = rounded_current_time + datetime.timedelta(minutes=self.time_step_minutes * i)

            # Get kW for this time-of-day bin
            power = avg_day_kw_lookup.get(point_time.time())

            # Fallback if missing
            if power is None or math.isnan(power) or power <= 0:
                power = avg_kw_per_bin

            forecast_power.append(
                BinnedStateClass(
                    avg_state=power,
                    states=[],
                    time=point_time
                )
            )

        return forecast_power
            
    def forecast_consumption_amount(self, forecast_hours_from_now=None, forecast_till_time=None):
        avg_day = self.get_load_avg(days_ago=self.load_avg_days)

        [rounded_current_time, rounded_forecast_time] = self.round_forecast_times(forecast_hours_from_now, forecast_till_time)

        # Lookup: time-of-day → kW per bin
        avg_day_kw_lookup = {bin.time: bin.avg_state for bin in avg_day}

        step_minutes = self.time_step_minutes
        forecast_steps = int(
            (rounded_forecast_time - rounded_current_time).total_seconds()
            // (step_minutes * 60)
        )
            
        total_kwh = 0.0

        avg_kw_per_bin = sum(b.avg_state for b in avg_day) / len(avg_day) # Used below to fallback if no data for specific bin

        for i in range(forecast_steps):
            point_time = rounded_current_time + datetime.timedelta(minutes=step_minutes * i)

            kw = avg_day_kw_lookup.get(point_time.time())

            # Fallback if missing
            if kw is None or math.isnan(kw):
                kw = avg_kw_per_bin

            total_kwh += kw * (step_minutes / 60)  # Convert kW to kWh for the time step

        return total_kwh
    
    def kwh_required_remaining(self, buffer_percentage=20):
        forecast_kwh = self.forecast_consumption_amount(forecast_till_time=datetime.time(6, 0, 0))
        return max(forecast_kwh, 0) * (1 + (buffer_percentage/100)) + 2
    
    def kwh_required_till_sundown(self, buffer_percentage=20):
        forecast_kwh = self.forecast_consumption_amount(forecast_till_time=datetime.time(18, 0, 0))
        return max(forecast_kwh, 0) * (1 + (buffer_percentage/100)) + 2
            
    # returns the forecast solar power for the requested time period in 5 minute increments
    def forecast_solar_power(self, forecast_hours_from_now, forecast_start_time=None, forecast_end_time=None):
        if forecast_start_time is not None and forecast_end_time is not None:
            rounded_start_time = round_minutes(forecast_start_time, nearest_minute=self.time_step_minutes)
            rounded_end_time = round_minutes(forecast_end_time, nearest_minute=self.time_step_minutes)
            forecast_seconds = max((rounded_end_time - rounded_start_time).total_seconds(), 0)
            forecast_hours = forecast_seconds / 3600
            N_5min = max(0, int(forecast_seconds // (self.time_step_minutes * 60)))
        else:
            forecast_hours = float(forecast_hours_from_now)
            N_5min = max(0, int(np.ceil(forecast_hours * (60 / self.time_step_minutes))))

        N_30min = max(0, int(np.ceil(N_5min / (30 // self.time_step_minutes))))
        interpolation_steps = 30 // self.time_step_minutes

        # Solar Forecast
        # Get solar forecast list from HA
        today = self.ha.get_state(config_manager.solcast_forecast_today_entity_id)["attributes"]["detailedForecast"]
        tomorrow = self.ha.get_state(config_manager.solcast_forecast_tomorrow_entity_id)["attributes"]["detailedForecast"]

        forecast = today + tomorrow # Combine

        if(forecast_hours > 24):
            day_3_forecast = self.ha.get_state(config_manager.solcast_forecast_day_3_entity_id)["attributes"]["detailedForecast"]
            forecast = forecast + day_3_forecast # Add day 3's forecast to the list if requesting more than 24 hrs of forecast
        
        if(forecast_hours > 48):
            day_4_forecast = self.ha.get_state(config_manager.solcast_forecast_day_4_entity_id)["attributes"]["detailedForecast"]
            forecast = forecast + day_4_forecast # Add day 4's forecast to the list if requesting more than 48 hrs of forecast
        
        df = pd.DataFrame(forecast) # Convert to DataFrame for easy time handling
        
        df["period_start"] = pd.to_datetime(df["period_start"]) # Parse timestamps (Solcast provides timezone-aware ISO strings)

        # Current time in same timezone
        if forecast_start_time is not None:
            now = pd.Timestamp(round_minutes(forecast_start_time, nearest_minute=self.time_step_minutes))
            if df["period_start"].dt.tz is not None and now.tzinfo is None:
                now = now.tz_localize(df["period_start"].dt.tz)
            elif df["period_start"].dt.tz is not None and now.tzinfo is not None:
                now = now.tz_convert(df["period_start"].dt.tz)
        else:
            now = pd.Timestamp.now(tz=df["period_start"].dt.tz)
            now = now.ceil(f"{self.time_step_minutes}min") #round to nearest time step

        # Keep only future (or current) periods
        df_future = (
            df[df["period_start"] >= now]
            .sort_values("period_start")
            .iloc[:N_30min]
        )

        # Solar forecast (kW)
        solar_30min = df_future["pv_estimate"].to_numpy()
        solar_30min = solar_30min[:N_30min]

        if len(solar_30min) == 0:
            logger.warning("Solcast returned no future 30 minute forecast intervals. Falling back to zero solar forecast.")
            return np.zeros(N_5min)

        if len(solar_30min) < N_30min:
            logger.warning(f"Solcast forecast shorter than requested horizon. Requested 30 min bins={N_30min}, received={len(solar_30min)}. Extending with last known value.")

        solar_30min_x = np.arange(0, len(solar_30min) * interpolation_steps, interpolation_steps)
        solar_5min = np.interp(np.arange(N_5min), solar_30min_x, solar_30min)
        
        return solar_5min[:N_5min] # return the solar forecast but limit the list length to the requested length

#from api_token_secrets import HA_URL, HA_TOKEN
#plant = Plant(HA_URL, HA_TOKEN, errors=True) 
#now = datetime.datetime.now(HA_TZ)
#hours = 1
#bin_period =5
#start = now - datetime.timedelta(hours=hours)
#end = now
#data_bin_qty = int((hours * 60) / 5)
#rouned_start_time = start.replace(minute=(start.minute // bin_period) * bin_period,second=0,microsecond=0,tzinfo=HA_TZ)
#history = plant.historical_data(hours=1)

#history = plant.ha.get_history(config_manager.solar_power_entity_id, start_time=start, end_time=end)
#rouned_start_time = start.replace(minute=(start.minute // 5) * 5,second=0,microsecond=0,tzinfo=HA_TZ)
#binned = plant.bin_data(history, bin_period, rouned_start_time, data_bin_qty)




#history = plant.plant_history(1)
#load = plant.forecast_load_power(forecast_hours_from_now=24)
#load = [round(load_state.avg_state) for load_state in load]
#print(load)
