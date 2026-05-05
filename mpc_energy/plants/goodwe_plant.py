import time
import datetime
from plants.base_plant import BasePlant
from mpc_logger import logger
from exceptions import HAAPIError, SigenergyConnectionError, PlantControlError

import data_helpers, config_manager


from ha_api import HomeAssistantAPI


class GoodWePlant(BasePlant):
    def __init__(self, ha: HomeAssistantAPI, optional_loads: list):
        super().__init__(ha, optional_loads)
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

        self.update_data()

        logger.debug(
                    f"Initialized SigEnergyPlant with the following parameters: | "
                    f"Battery Capacity: {self.rated_capacity} kWh | "
                    f"Max Discharge: {self.max_discharge_power} kW | "
                    f"Max Charge: {self.max_charge_power} kW | "
                    f"Max PV: {self.max_pv_power} kW | "
                    f"Max Inverter: {self.max_inverter_power} kW | "
                    f"Max Export: {self.max_export_power} kW | "
                    f"Max Import: {self.max_import_power} kW | "
                    f"Backup Buffer: {self.kwh_backup_buffer} kWh"
                )
        
    def get_sigenergy_state(self, entity_id) -> str:
        """Fetches the state of the specified entity from Home Assistant. Raises an error if the entity is unavailable."""
        state_payload = self.ha.get_state(entity_id)
        if isinstance(state_payload, dict) and state_payload.get("state") == "unavailable":
            raise SigenergyConnectionError(
                f"Sigenergy system is unavailable (entity: '{entity_id}'). "
                "It is likely offline or has a bad connection."
            ) from None
        return state_payload

    def get_sigenergy_numeric_state(self, entity_id) -> float:
        """Fetches the state of the specified entity from Home Assistant and converts it to a float. Raises an error if the entity is unavailable or the state cannot be converted to a float."""
        state_payload = self.get_sigenergy_state(entity_id)
        state = state_payload.get("state") if isinstance(state_payload, dict) else None
        try:
            return float(state)
        except (TypeError, ValueError):
            raise HAAPIError(
                f"Unable to convert state '{state}' for entity '{entity_id}' to float."
            ) from None

    def get_plant_mode(self) -> str:
        """Returns the current control mode of the plant."""
        return self.get_sigenergy_state(config_manager.ems_control_mode_entity_id)["state"]
    
    def update_data(self) -> None:
        """Update the plant's data by fetching the latest states from Home Assistant."""
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
        #self.solar_kwh_today = self.get_sigenergy_numeric_state(config_manager.plant_solar_kwh_today_entity_id) # Commented out as it is not used in current implementation.
        self.solar_kw_remaining_today = self.get_sigenergy_numeric_state(config_manager.solcast_solar_kwh_remaining_today_entity_id)
        self.inverter_power = self.get_sigenergy_numeric_state(config_manager.inverter_power_entity_id)
        self.grid_power = self.get_sigenergy_numeric_state(config_manager.grid_power_entity_id)
        self.load_power = self.get_sigenergy_numeric_state(config_manager.load_power_entity_id)
        self.avg_daily_load = sum(bin.avg_state*(self.time_step_minutes/60) for bin in self.get_load_avg(days_ago=self.load_avg_days))
        

        self.calculate_today_profit_cost()
        
        self.hours_till_full = 0
        self.hours_till_empty = 0
        if(self.battery_kw < 0):
            self.hours_till_full = round(self.kwh_till_full / abs(self.battery_kw), 2)
        elif(self.battery_kw > 0):
            self.hours_till_empty = round(self.kwh_stored_available / abs(self.battery_kw), 2)

    def ensure_remote_ems(self) -> None: 
        """Ensures the remote EMS switch is on provided the automatic control switch is on"""
        if(self.get_sigenergy_state(config_manager.ha_ems_control_switch_entity_id)['state'] != "on"):
                logger.warning(f"Remote EMS switch is '{self.get_sigenergy_state(config_manager.ha_ems_control_switch_entity_id)['state']}', turning on to allow control.")
                self.ha.set_switch_state(config_manager.ha_ems_control_switch_entity_id, True)
                time.sleep(10) # delay to ensure the change has time to become effective

    def set_control_limits(self, control_mode: str, discharge: float, charge: float, pv: float, grid_export: float, grid_import: float) -> None:
        """Set the control limits to the desired values."""

        self.ensure_remote_ems() # Make sure the EMS is able to be controlled

        self.ha.set_number(config_manager.battery_discharge_limiter_entity_id, discharge)
        self.ha.set_number(config_manager.battery_charge_limiter_entity_id, charge)
        self.ha.set_number(config_manager.pv_limiter_entity_id, pv)
        self.ha.set_number(config_manager.export_limiter_entity_id, grid_export)
        self.ha.set_number(config_manager.import_limiter_entity_id, grid_import)
        
        if(control_mode in self.control_mode_options):
            self.ha.set_select(config_manager.ems_control_mode_entity_id, control_mode)
        else:
            raise ValueError(f"Requested control mode '{control_mode}' is not a valid control mode!")
    
    def check_control_limits(self, working_mode: str, control_mode: str, discharge: float, charge: float, pv: float, grid_export: float, grid_import: float) -> None:
        """Check if control limits match desired values and change them if required."""
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
    
    def check_for_enabled_entites(self) -> None:
        """Checks to make sure all the entities needed for control are available and enabled, if not it raises an error."""
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

    def system_curtailing(self, derate_allowance_kw=1.0, tolerance_kw=0.1) -> dict:
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

    def historical_data(self, start_datetime=None, end_datetime=None, hours=None, bin_period=5) -> list[data_helpers.BinnedStateClass]:
        """
        Get the requested hours of historical data for the plant being (SOC, battery power, inverter power, solar power, grid power, load power and prices.) in order oldest to newest
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
            rounded_now = data_helpers.round_minutes(time=now, nearest_minute=bin_period)
            start_datetime = data_helpers.round_minutes(time=rounded_now - datetime.timedelta(hours=hours), nearest_minute=bin_period)
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

        grid_power_state_history = self.ha.get_history(config_manager.grid_power_entity_id, start_time=start_datetime, end_time=end_datetime)
        grid_import_kwh_state_history = self.ha.get_history(config_manager.plant_daily_import_kwh_entity_id, start_time=start_datetime, end_time=end_datetime)
        grid_export_kwh_state_history = self.ha.get_history(config_manager.plant_daily_export_kwh_entity_id, start_time=start_datetime, end_time=end_datetime)

        feed_in_state_history = self.ha.get_history("sensor.mpc_energy_manager_device_feed_in_price", start_time=start_datetime, end_time=end_datetime) 
        general_price_state_history = self.ha.get_history("sensor.mpc_energy_manager_device_general_price", start_time=start_datetime, end_time=end_datetime)
        working_mode_state_history = self.ha.get_history("sensor.mpc_energy_manager_device_working_mode", start_time=start_datetime, end_time=end_datetime, type=str)

        #requested_data_received = self.validate_returned_data_timedelta(inverter_power_state_history, start_datetime, end_datetime)


        binned_battery_soc_state_history = data_helpers.bin_data(battery_soc_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime)
        binned_battery_power_state_history = data_helpers.bin_data(battery_power_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime)
        binned_inverter_power_state_history = data_helpers.bin_data(inverter_power_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime)
        binned_load_power_state_history = data_helpers.bin_data(load_power_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime)
        
        binned_solar_power_state_history = data_helpers.bin_data(solar_power_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime)
        binned_grid_power_state_history = data_helpers.bin_data(grid_power_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime)

        binned_grid_import_kwh_state_history = data_helpers.bin_data(grid_import_kwh_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime)
        binned_grid_export_kwh_state_history = data_helpers.bin_data(grid_export_kwh_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime)

        
        binned_feed_in_state_history = data_helpers.bin_data(feed_in_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime, interpolation_method="step")
        binned_general_price_state_history = data_helpers.bin_data(general_price_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime, interpolation_method="step")# Step Interpolation as prices dont gradually change
        binned_working_mode_state_history = data_helpers.bin_data(working_mode_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime, string_state=True)

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
            "grid_power": [state.avg_state for state in binned_grid_power_state_history],
            "prices_sell": [state.avg_state/100.0 for state in binned_feed_in_state_history], # Converted to dollars from cents
            "prices_buy": [state.avg_state/100.0 for state in binned_general_price_state_history],
            "plan_modes": [state.avg_state for state in binned_working_mode_state_history],
            "grid_import_kwh": [state.avg_state for state in binned_grid_import_kwh_state_history],
            "grid_export_kwh": [state.avg_state for state in binned_grid_export_kwh_state_history],
        }
        return output


