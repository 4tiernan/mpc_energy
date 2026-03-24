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
from exceptions import HAAPIError, SigenergyConnectionError
import traceback


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
        
        #print(f"Battery Cap: {self.rated_capacity} kWh | Max Discharge: {self.max_discharge_power} kW | Max Charge: {self.max_charge_power} kW | Max PV: {self.max_pv_power} kW | Max Inverter: {self.max_inverter_power} kW | Max Export: {self.max_export_power} kW | Max Import: {self.max_import_power} kW")
        self.load_avg_days = 3

        self.last_load_data_retrival_timestamp = 0
        self.avg_load_day = None

        self.last_base_load_estimate_timestamp = 0
        self.base_load_estimate = None

        self.history_since_midnight = None

        self.update_data()

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
        self.solar_daytime = self.get_sigenergy_numeric_state(config_manager.solcast_solar_power_this_hour_entity_id) > self.get_base_load_estimate() # If producing more power than base load consider it during the solar day
        self.inverter_power = self.get_sigenergy_numeric_state(config_manager.inverter_power_entity_id)
        self.grid_power = self.get_sigenergy_numeric_state(config_manager.grid_power_entity_id)
        self.load_power = self.get_sigenergy_numeric_state(config_manager.load_power_entity_id)
        self.avg_daily_load = self.get_load_avg(days_ago=self.load_avg_days)[-1].avg_state

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
    
    def historical_data(self, hours, bin_period=5): # Get the requested hours of historical data for the plant being (SOC, battery power, inverter power, solar power, grid power, load power and prices.) in order oldest to newest
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
        now = datetime.datetime.now(self.local_tz)
        rounded_now = self.round_minutes(time=now, nearest_minute=bin_period)
        start = self.round_minutes(time=rounded_now - datetime.timedelta(hours=hours), nearest_minute=bin_period)
        end = now
        data_bin_qty = int((hours * 60) / bin_period) + 1 # +1 to captre the end time otherwise it would only get the 2nd last time

        battery_soc_state_history = self.ha.get_history(config_manager.battery_soc_entity_id, start_time=start, end_time=end)
        battery_power_state_history = self.ha.get_history(config_manager.battery_power_entity_id, start_time=start, end_time=end)
        if(config_manager.battery_power_sign_convention == "+ Charge, - Discharge"):
            for state in battery_power_state_history:
                try:
                    state.state = -float(state.state)
                except:
                    pass
        # Internal battery power convention ^^^^^^^:
        #   +kW = discharging (battery supplying power)
        #   -kW = charging (battery absorbing power)

        inverter_power_state_history = self.ha.get_history(config_manager.inverter_power_entity_id, start_time=start, end_time=end)
        solar_power_state_history = self.ha.get_history(config_manager.solar_power_entity_id, start_time=start, end_time=end)
        load_power_state_history = self.ha.get_history(config_manager.load_power_entity_id, start_time=start, end_time=end)
        grid_power_state_history = self.ha.get_history(config_manager.grid_power_entity_id, start_time=start, end_time=end)
        grid_import_kwh_state_history = self.ha.get_history(config_manager.plant_daily_import_kwh_entity_id, start_time=start, end_time=end)
        grid_export_kwh_state_history = self.ha.get_history(config_manager.plant_daily_export_kwh_entity_id, start_time=start, end_time=end)

        feed_in_state_history = self.ha.get_history("sensor.mpc_energy_manager_device_feed_in_price", start_time=start, end_time=end) 
        general_price_state_history = self.ha.get_history("sensor.mpc_energy_manager_device_general_price", start_time=start, end_time=end)
        working_mode_state_history = self.ha.get_history("sensor.mpc_energy_manager_device_working_mode", start_time=start, end_time=end, type=str)

        #requested_data_received = self.validate_returned_data_timedelta(inverter_power_state_history, start, end)


        binned_battery_soc_state_history = self.bin_data(battery_soc_state_history, bin_period=bin_period, start_bin_datetime=start, bin_qty=data_bin_qty)
        binned_battery_power_state_history = self.bin_data(battery_power_state_history, bin_period=bin_period, start_bin_datetime=start, bin_qty=data_bin_qty)
        binned_inverter_power_state_history = self.bin_data(inverter_power_state_history, bin_period=bin_period, start_bin_datetime=start, bin_qty=data_bin_qty)
        binned_solar_power_state_history = self.bin_data(solar_power_state_history, bin_period=bin_period, start_bin_datetime=start, bin_qty=data_bin_qty)
        binned_load_power_state_history = self.bin_data(load_power_state_history, bin_period=bin_period, start_bin_datetime=start, bin_qty=data_bin_qty)
        binned_grid_power_state_history = self.bin_data(grid_power_state_history, bin_period=bin_period, start_bin_datetime=start, bin_qty=data_bin_qty)

        binned_grid_import_kwh_state_history = self.bin_data(grid_import_kwh_state_history, bin_period=bin_period, start_bin_datetime=start, bin_qty=data_bin_qty)
        binned_grid_export_kwh_state_history = self.bin_data(grid_export_kwh_state_history, bin_period=bin_period, start_bin_datetime=start, bin_qty=data_bin_qty)

        
        binned_feed_in_state_history = self.bin_data(feed_in_state_history, bin_period=bin_period, start_bin_datetime=start, bin_qty=data_bin_qty, interpolation_method="step")
        binned_general_price_state_history = self.bin_data(general_price_state_history, bin_period=bin_period, start_bin_datetime=start, bin_qty=data_bin_qty, interpolation_method="step")# Step Interpolation as prices dont gradually change
        binned_working_mode_state_history = self.bin_data(working_mode_state_history, bin_period=bin_period, start_bin_datetime=start, bin_qty=data_bin_qty, string_state=True)

        binned_battery_soc_kwh_history = [(item.avg_state / 100.0) * self.rated_capacity for item in binned_battery_soc_state_history]
        
        history_time_index = [item.time.isoformat() for item in binned_battery_soc_state_history] # Get the time marks from the data

        output = {
            "time_index": history_time_index,
            "soc": binned_battery_soc_kwh_history,
            "battery_power": [state.avg_state for state in binned_battery_power_state_history],
            "inverter_power": [state.avg_state for state in binned_inverter_power_state_history],
            "solar_power": [state.avg_state for state in binned_solar_power_state_history],
            "load_power": [state.avg_state for state in binned_load_power_state_history],
            "grid_power": [state.avg_state for state in binned_grid_power_state_history],
            "prices_sell": [state.avg_state/100.0 for state in binned_feed_in_state_history], # Converted to dollars from cents
            "prices_buy": [state.avg_state/100.0 for state in binned_general_price_state_history],
            "plan_modes": [state.avg_state for state in binned_working_mode_state_history],
            "grid_import_kwh": [state.avg_state for state in binned_grid_import_kwh_state_history],
            "grid_export_kwh": [state.avg_state for state in binned_grid_export_kwh_state_history],
        }
        return output
    
    def get_profit_history(self): #Get the history required for the profit calcs and use cached data if its not too old to avoid the expensive historical data retrieval and processing if possible.
        if self.history_since_midnight == None:
            start = datetime.datetime.now(self.local_tz).replace(hour=0, minute=0, second=0, microsecond=0)
            end = datetime.datetime.now(self.local_tz)
            hours_since_midnight = (end - start).total_seconds() / 3600
            self.history_since_midnight = self.historical_data(hours=hours_since_midnight, bin_period=5)
            return self.history_since_midnight
        else:
            last_history_timestamp = self.history_since_midnight['time_index'][-1]
            start = datetime.datetime.fromisoformat(last_history_timestamp)
            end = datetime.datetime.now(self.local_tz)
            hours_since_last_history = (end - start).total_seconds() / 3600
            if hours_since_last_history > 4/60: # If the history is more than 4 minutes old, get new history
                latest_history = self.historical_data(hours=hours_since_last_history, bin_period=5)

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
        logger.info(f"Latest history data: {self.history_since_midnight['time_index'][-10:]}")
        return self.history_since_midnight

    def calculate_today_profit_cost(self):
        # Get today's historical data
        history = self.get_profit_history()

        # Check to see if the requested amount of data was recieved, use the configured default if not
        if(len(history['prices_sell']) < 2):
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

    def display_data(self):
        self.update_data()
        logger.info("Stored Energy: "+str(round(self.kwh_stored_energy,2))+" kWh")
        logger.info("Available Stored Energy: "+str(round(self.kwh_stored_available,2))+" kWh")
        logger.info("kWh till Full: "+str(round(self.kwh_till_full,2))+" kWh")
        logger.info(f"Hours Till Full: {self.display_hrs_minutes(self.hours_till_full)}")
        logger.info(f"Hours Till Empty: {self.display_hrs_minutes(self.hours_till_empty)}")

    def display_hrs_minutes(self, hours):
        if(hours < 1):
            return f"{round(hours*60)} minutes"
        elif(hours%1 == 0):
            return f"{int(hours)} hours"
        else:   
            return f"{int(hours)} hours {round((hours%1)*60)} minutes"

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
            logger.info(f"{working_mode} !!!")
            time.sleep(5) # Allow time for HA to update
    
    def ensure_remote_ems(self): # Ensures the remote EMS switch is on provided the automatic control switch is on
        if(self.get_sigenergy_state(config_manager.ha_ems_control_switch_entity_id)['state'] != "on"):
                logger.warning(f"Remote EMS switch is '{self.get_sigenergy_state(config_manager.ha_ems_control_switch_entity_id)['state']}', turning on to allow control.")
                self.ha.set_switch_state(config_manager.ha_ems_control_switch_entity_id, True)
                time.sleep(2) # delay to ensure the change has time to become effective

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
    
    def calculate_base_load(self, days_ago = 7): # Calculate base load in kW
        today = datetime.datetime.now(self.local_tz).date()
        end_date = today - datetime.timedelta(days=1)
        start_date = end_date - datetime.timedelta(days=days_ago)

        start = datetime.datetime.combine(start_date, datetime.time.min, tzinfo=self.local_tz)
        end = datetime.datetime.combine(end_date, datetime.time.min, tzinfo=self.local_tz)

        load_state_history = self.ha.get_history(config_manager.load_power_entity_id, start_time=start, end_time=end)

        # Check to see if the requested amount of data was recieved, use the configured default if not
        if(not self.validate_returned_data_timedelta(data=load_state_history, requested_start=start, requested_end=end)):
            configured_avg_load_power = config_manager.estimated_daily_load_energy_consumption / 24 # Divide by 24 to convert from daily energy to power
            logger.warning(f"Using default load power of {configured_avg_load_power} kW for the base load.")
            return configured_avg_load_power
        
        # If we get here the requested amount of data must have been received. 
        load_history = [h.state for h in load_state_history]
        
        load_history_clean = [
            v for v in load_history
            if v is not None and not math.isnan(v)
        ]
        self.base_load_estimate = np.percentile(load_history_clean, 20)

        return self.base_load_estimate

    def get_base_load_estimate(self, days_ago = 7, hours_update_interval=24): # Returns approximate base load in kW
        if(time.time() - self.last_base_load_estimate_timestamp > hours_update_interval*60*60 or self.base_load_estimate == None):
            self.base_load_estimate = self.calculate_base_load(days_ago)
            self.last_base_load_estimate_timestamp = time.time()
        return self.base_load_estimate
    
    def interpolate_values(self, values, method="linear"):
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

    def bin_data(self, history, bin_period, start_bin_datetime, bin_qty, string_state=False, interpolation_method="linear"): 
        """
        history[x].state    -> numeric value (string or float)
        history[x].time     -> datetime object (tz-aware)
        start_bin_datetime  -> datetime object for bin start time
        bin_period          -> time period (minutes) to bin data into
        bin_qty             -> total qty of bins to be outputted

        Returns:
            List of BinnedStateClass objs:
            [
                bin.time": bin_start_datetime,
                bin.avg_state": average_value_in_bin
                ...
            ]
        """
        bin_delta = datetime.timedelta(minutes=bin_period)

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

        #dt = datetime.datetime.combine(datetime.date.today(), datetime.time.min) # Time for start of day, ie 00:01

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

        '''for state in clean_history: 
            # Round the state's time to the nearest time bin
            state.time = state.time.replace(
                minute=(state.time.minute // bin_period) * bin_period,
                second=0,
                microsecond=0,
                tzinfo=HA_TZ
                )
            #print(f"State: {state.time}  bin:{binned_history[i].time} Equal:{state.time.time() == binned_history[i].time.time()}")
                            
            # If it doesn't match, then it should belong in the next bin, thus increment to the next bin
            if(state.time.time() != binned_history[i].time.time()): 
                if(i < len(binned_history)-1):
                    i = i+1

            # If the state's rounded time matches the current array time bin, add it to the array
            if(state.time.time() == binned_history[i].time.time()):
                if(state.state != None):
                    binned_history[i].states.append(state.state)'''


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
                logger.warning(f"{expected_span.days} days of load data was requested but only {actual_span.days} were returned")
                return False
        return True

    def update_load_avg(self, days_ago=7):
        avg_day = [] # Create the avg day array to contain the average load energy profile
        dt = datetime.datetime.combine(
            datetime.date.today(),
            datetime.time.min
        )
        time_bucket_size = 5 # Size of time bucket in Minutes 

        for i in range(int((24*60)/time_bucket_size)):
            avg_day.append(BinnedStateClass(avg_state=None, states=[], time=dt.time()))
            dt = dt + datetime.timedelta(minutes=time_bucket_size)


        today = datetime.datetime.now(self.local_tz).date()
        end_date = today - datetime.timedelta(days=1)
        start_date = end_date - datetime.timedelta(days=days_ago)

        start = datetime.datetime.combine(start_date, datetime.time.min, tzinfo=self.local_tz)
        end = datetime.datetime.combine(end_date, datetime.time.min, tzinfo=self.local_tz)


        history = self.ha.get_history(config_manager.plant_daily_load_kwh_entity_id, start_time=start, end_time=end)
        
        # Check to see if the requested amount of data was recieved, use the configured default if not
        if(not self.validate_returned_data_timedelta(data=history, requested_start=start, requested_end=end)):
            configured_avg_load = config_manager.estimated_daily_load_energy_consumption 
            logger.warning(f"Using default load energy of {configured_avg_load} kWh per day.")

            # Create a linearly spaced array climbing from 0 to the total load over a day
            for i in range(len(avg_day)):
                    avg_day[i].avg_state = (i/len(avg_day)) * configured_avg_load

            return avg_day 
        

        # If we've got here we must have the requested number of days of load data     

        # Remove any invalid states from the history list (Unavailable, None, etc)
        clean_history = []
        for hist in history:
            try:
                if hist.state is not None:
                    hist.state = float(hist.state)
                    clean_history.append(hist)
            except (ValueError, TypeError):
                pass  # drop unknown/unavailable/etc
        

        day = 0
        history_days = [[]]
        for hist in clean_history: 
            if(hist.time.date() == start_date + datetime.timedelta(days=day)):
                history_days[day].append(hist)
            elif(hist.time.date() == start_date + datetime.timedelta(days=day+1)):
                day = day + 1
                history_days.append([])
                history_days[day].append(hist)

        for day in history_days:
            day_states = [d.state for d in day]
            min_state = min(day_states[0:int(len(day_states)/2)]) # Minimum state for first half of day (avoids getting next days minimum)
            max_state = max(day_states[int(len(day_states)/2):-1]) # Maximum state for second half of day (avoids getting next days minimum)

            while(day[0].state > min_state): # remove any states that were from the previous day, ie ensure we start with 0 for the day
                day.pop(0)
                #print("Popping Start of Day Data")
            
            while(day[-1].state < max_state): # remove any states that were from the previous day, ie ensure we start with 0 for the day
                day.pop(-1)
                #print("Popping End of Day Data")
        
        for day in history_days:
            i = 0
            bin_avg = []
            for state in day: 
                # Round the state's time to the nearest time bin
                state.time = state.time.replace(
                    minute=(state.time.minute // time_bucket_size) * time_bucket_size,
                    second=0,
                    microsecond=0,
                    tzinfo=self.local_tz
                    )
                                
                # If it doesn't match, then it should belong in the next bin, thus increment to the next bin
                if(state.time.time() != avg_day[i].time): 
                    if(i < len(avg_day)-1):
                        if(state.time.time() == avg_day[i+1].time):
                            if(len(bin_avg) > 0):
                                avg_day[i].states.append(sum(bin_avg) / len(bin_avg)) # Append the average for this day's time bin
                            else:
                                avg_day[i].states.append(None) # Make the state 0 if we have no data for it 
                            bin_avg = []
                            i = i + 1
                        else: # If the time we are after isn't in the next bin then there musn't be data there
                            avg_day[i].states.append(None) # Make the state 0 if we have no data for it 
                            i = i + 1

                # If the state's rounded time matches the current array time bin, add it to the array
                if(state.time.time() == avg_day[i].time):
                    if(state.state != None):
                        bin_avg.append(state.state)

            if(len(bin_avg) > 0):                    
                avg_day[i].states.append(sum(bin_avg) / len(bin_avg))   # calc avg for last period of day         

        #for interval in avg_day:
        #    print(interval.states)

        def state_for_interval(interval_index, state_index): # Safe state interval retrival
            if(interval_index < 0 or interval_index >= len(avg_day)):
                return None
            if(state_index < 0 or state_index >= len(avg_day[interval_index].states)):
                return None
            return avg_day[interval_index].states[state_index]
        
        for index, interval in enumerate(avg_day):
            for state_index, state in enumerate(avg_day[index].states): # Check all days states for that time have data
                if(state == None): # If there's no data for that day's state, take the avg of the last and next states for that day
                    last_state = None
                    next_state = None
                    lower_idx = index - 1
                    while(last_state == None and lower_idx > 1): # Find the last two valid states for that day (2 states increases likelyhood they are vaild)
                        if(state_for_interval(lower_idx, state_index) != None and state_for_interval(lower_idx-1, state_index) != None):
                            lower_idx = lower_idx - 1 # reduce the index to get the 2nd valid state
                            last_state = avg_day[lower_idx].states[state_index]
                        else:
                            lower_idx = lower_idx - 1

                    upper_idx = index + 1
                    while(next_state == None and upper_idx < len(avg_day)-2): # Find the next valid two states for that day
                        if(state_for_interval(upper_idx, state_index) != None and state_for_interval(upper_idx+1, state_index) != None):
                            upper_idx = upper_idx + 1
                            next_state = state_for_interval(upper_idx, state_index)
                        else:
                            upper_idx = upper_idx + 1
                    
                    #print(f"next: {next_state} last: {last_state} idx: {index}")
                    if(next_state != None and last_state != None): # If both states are present, linearly interpolate between them
                        n = upper_idx - lower_idx # Determine the linear interpolated values to fill the missing data
                        for i in range(lower_idx, upper_idx + 1):
                            avg_day[i].states[state_index] = last_state + (next_state - last_state) * ((i - lower_idx) / n)
                            #print(last_state + ((next_state - last_state) * (i - lower_idx)) / n)
                    elif(last_state != None):
                        avg_day[index].states[state_index] = state_for_interval(index-1, state_index) # Use just the last state if the next state isn't available
                    elif(next_state != None):
                        avg_day[index].states[state_index] = state_for_interval(index+1, state_index) # Use just the next state if the last state isn't available

            interval = avg_day[index] # Update the interval var with the latest data after cleaning
        
        configured_avg_load = config_manager.estimated_daily_load_energy_consumption
        last_known_avg_state = None
        for index, interval in enumerate(avg_day):
            valid_states = [state for state in interval.states if state is not None]
            if(len(valid_states) == 0):
                configured_interval_avg = round((index / len(avg_day)) * configured_avg_load, 2)
                interval.avg_state = configured_interval_avg
                if(last_known_avg_state is not None):
                    interval.avg_state = max(last_known_avg_state, configured_interval_avg)
                logger.warning(f"Using configured fallback load for {interval.time} time period")
                last_known_avg_state = interval.avg_state
            
            else:
                interval.avg_state = round(sum(valid_states) / len(valid_states), 2)
                last_known_avg_state = interval.avg_state


            #print(f"avg: {interval.state} states: {interval.states}")

        #for i in range(len(avg_day)): # Print average for each day and each time
        #    print(avg_day[i].state)
        #    print(avg_day[i].states)       

        return avg_day

    def round_forecast_times(self, forecast_hours_from_now=None, forecast_till_time=None):
        rounded_current_time = self.round_minutes(datetime.datetime.now(self.local_tz), nearest_minute=5)
        if(forecast_hours_from_now):
            rounded_forecast_time = self.round_minutes(rounded_current_time + datetime.timedelta(hours=forecast_hours_from_now), nearest_minute=5)
        elif(forecast_till_time):
            rounded_forecast_time = datetime.datetime.combine(rounded_current_time.date(), forecast_till_time, tzinfo=self.local_tz)
            rounded_forecast_time = self.round_minutes(rounded_forecast_time, nearest_minute=5)
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
    
    def forecast_load_power(self, forecast_hours_from_now=None, forecast_till_time=None):
        avg_day = self.get_load_avg(days_ago=self.load_avg_days)

        # Determine the current and the end of the forecast datetimes, both rounded to 5 min
        [rounded_current_time, rounded_forecast_time] = self.round_forecast_times(forecast_hours_from_now, forecast_till_time)

        # Create a lookup dict for each time bin
        avg_day_kwh_lookup = {bin.time: bin.avg_state for bin in avg_day}
        avg_day_total_kwh = avg_day[-1].avg_state

        # Get the appropriate kwh for the provided time
        def cumulative_kwh_for_time(target_time):
            day_offset = (target_time.date() - rounded_current_time.date()).days
            return avg_day_kwh_lookup[target_time.time()] + (day_offset * avg_day_total_kwh)

        forecast_power = []
        forecast_steps = int((rounded_forecast_time - rounded_current_time).total_seconds() // (5 * 60))

        # Loop through the forecast and fill the forecast array as the kwh between the current and next time divided by the time step
        for i in range(forecast_steps):
            point_time = rounded_current_time + datetime.timedelta(minutes=5 * i)
            if(i == 0 and forecast_steps > 1):
                next_time = point_time + datetime.timedelta(minutes=5)
                power = (cumulative_kwh_for_time(next_time) - cumulative_kwh_for_time(point_time)) / (5/60)
            else:
                prev_time = point_time - datetime.timedelta(minutes=5)
                power = (cumulative_kwh_for_time(point_time) - cumulative_kwh_for_time(prev_time)) / (5/60)

            if(power <= 0):
                power = avg_day_total_kwh / 24 #If we get a weird reading, replace it with the average

            forecast_power.append(BinnedStateClass(avg_state=power, states=[], time=point_time))
        
        return forecast_power
            
    def forecast_consumption_amount(self, forecast_hours_from_now=None, forecast_till_time=None):
        avg_day = self.get_load_avg(days_ago=self.load_avg_days)

        [rounded_current_time, rounded_forecast_time] = self.round_forecast_times(forecast_hours_from_now, forecast_till_time)
    
        avg_day_kwh_lookup = {bin.time: bin.avg_state for bin in avg_day}
        avg_day_total_kwh = avg_day[-1].avg_state

        starting_kwh = avg_day_kwh_lookup[rounded_current_time.time()]
        day_offset = (rounded_forecast_time.date() - rounded_current_time.date()).days
        ending_kwh = avg_day_kwh_lookup[rounded_forecast_time.time()] + (day_offset * avg_day_total_kwh)

        return ending_kwh - starting_kwh
    
    def kwh_required_remaining(self, buffer_percentage=20):
        forecast_kwh = self.forecast_consumption_amount(forecast_till_time=datetime.time(6, 0, 0))
        return max(forecast_kwh, 0) * (1 + (buffer_percentage/100)) + 2
    
    def kwh_required_till_sundown(self, buffer_percentage=20):
        forecast_kwh = self.forecast_consumption_amount(forecast_till_time=datetime.time(18, 0, 0))
        return max(forecast_kwh, 0) * (1 + (buffer_percentage/100)) + 2
        
    def round_minutes(self, time, nearest_minute):
        return time.replace(
            minute=(time.minute // nearest_minute) * nearest_minute,
            second=0,
            microsecond=0
            )  
    
    # returns the forecast solar power for the requested time period in 5 minute increments
    def forecast_solar_power(self, forecast_hours_from_now):
        N_30min = forecast_hours_from_now * (60//30)
        N_5min = forecast_hours_from_now * (60//5)
        interpolation_steps = 30//5

        # Solar Forecast
        # Get solar forecast list from HA
        today = self.ha.get_state(config_manager.solcast_forecast_today_entity_id)["attributes"]["detailedForecast"]
        tomorrow = self.ha.get_state(config_manager.solcast_forecast_tomorrow_entity_id)["attributes"]["detailedForecast"]

        forecast = today + tomorrow # Combine

        if(forecast_hours_from_now > 24):
            day_3_forecast = self.ha.get_state(config_manager.solcast_forecast_day_3_entity_id)["attributes"]["detailedForecast"]
            forecast = forecast + day_3_forecast # Add day 3's forecast to the list if requesting more than 24 hrs of forecast
        
        df = pd.DataFrame(forecast) # Convert to DataFrame for easy time handling
        
        df["period_start"] = pd.to_datetime(df["period_start"]) # Parse timestamps (Solcast provides timezone-aware ISO strings)

        # Current time in same timezone
        now = pd.Timestamp.now(tz=df["period_start"].dt.tz)
        now = now.ceil("5min") #round to nearest 5 min

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
