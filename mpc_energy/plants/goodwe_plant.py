import time
import datetime
from plants.base_plant import BasePlant
from mpc_logger import logger
from exceptions import HAAPIError, GoodWeConnectionError, MPCEnergyError
import data_helpers, config_manager
from ha_api import HomeAssistantAPI

class GoodWePlant(BasePlant):
    def __init__(self, ha: HomeAssistantAPI, optional_loads: list, plant_config: dict = None):
        super().__init__(ha, optional_loads, plant_config)

        self.get_config(plant_config)

        self.check_for_enabled_entities() # Check to make sure all the required entities are enabled before starting the app to prevent issues later on.
        
        # Initialize power limits and capacity using configuration overrides where available
        self.rated_capacity = self.get_config_entry_value(self.battery_rated_capacity_entry)
        self.max_discharge_power = self.get_power_config_entry_value(self.battery_max_discharge_power_limit_entry)
        self.max_charge_power = self.get_power_config_entry_value(self.battery_max_charge_power_limit_entry)
        self.max_pv_power = self.get_power_config_entry_value(self.pv_max_power_limit_entry)
        self.max_inverter_power = self.get_power_config_entry_value(self.inverter_max_power_limit_entry)
        self.max_export_power = self.get_power_config_entry_value(self.export_max_power_limit_entry)
        self.max_import_power = self.get_power_config_entry_value(self.import_max_power_limit_entry)       

        
        self.control_mode_options = [
            "Auto",
            "Charge PV",
            "Discharge PV",
            "Import AC",
            "Export AC",
            "Conserve",
            "Off-grid",
            "Battery Standby",
            "Buy Power",
            "Sell Power",
            "Charge Battery",
            "Discharge Battery"
        ]

        self.update_data()

        logger.debug(
                    f"Initialized GoodWePlant with the following parameters: | "
                    f"Battery Capacity: {self.rated_capacity} kWh | "
                    f"Max Discharge: {self.max_discharge_power} kW | "
                    f"Max Charge: {self.max_charge_power} kW | "
                    f"Max PV: {self.max_pv_power} kW | "
                    f"Max Inverter: {self.max_inverter_power} kW | "
                    f"Max Export: {self.max_export_power} kW | "
                    f"Max Import: {self.max_import_power} kW | "
                    f"Backup SOC: {self.get_config_entry_value(self.backup_soc_entry)}% | "
                    f"Charge Cutoff SOC: {self.get_config_entry_value(self.charge_cutoff_soc_entry)}%"
                )

    def get_config(self, plant_config: dict) -> None:
        self.battery_rated_capacity_entry = plant_config.get("battery_rated_capacity_entry")
        self.battery_max_discharge_power_limit_entry = plant_config.get("battery_max_discharge_power_limit_entry")
        self.battery_max_charge_power_limit_entry = plant_config.get("battery_max_charge_power_limit_entry")
        self.pv_max_power_limit_entry = plant_config.get("pv_max_power_limit_entry")
        self.inverter_max_power_limit_entry = plant_config.get("inverter_max_power_limit_entry")
        self.export_max_power_limit_entry = plant_config.get("export_max_power_limit_entry")
        self.import_max_power_limit_entry = plant_config.get("import_max_power_limit_entry")   
        self.backup_soc_entry = plant_config.get("backup_soc_entry")
        self.charge_cutoff_soc_entry = plant_config.get("charge_cutoff_soc_entry")

        self.battery_soc_entity_id = plant_config.get("battery_soc_entity_id")
        self.battery_power_entity_id = plant_config.get("battery_power_entity_id")
        self.solar_power_entity_id = plant_config.get("solar_power_entity_id")
        self.load_power_entity_id = plant_config.get("load_power_entity_id")
        self.grid_power_entity_id = plant_config.get("grid_power_entity_id")
        self.battery_power_sign_convention = plant_config.get("battery_power_sign_convention")
        self.grid_power_sign_convention = plant_config.get("grid_power_sign_convention")

        self.plant_daily_import_kwh_entity_id = plant_config.get("plant_daily_import_kwh_entity_id")
        self.plant_daily_export_kwh_entity_id = plant_config.get("plant_daily_export_kwh_entity_id")
        self.grid_export_limit_switch_entity_id = plant_config.get("grid_export_limit_switch_entity_id")
        self.export_limiter_entity_id = plant_config.get("export_limiter_entity_id")
        self.ems_power_limit_entity_id = plant_config.get("ems_power_limit_entity_id")
        self.ems_control_mode_entity_id = plant_config.get("ems_control_mode_entity_id")

    def get_plant_mode(self) -> str:
        """Returns the current control mode of the plant."""
        return self.get_safe_state(self.ems_control_mode_entity_id)["state"]

    def update_data(self) -> None:
        """Update the plant's data by fetching the latest states from Home Assistant."""
        self.battery_soc_percent = self.get_safe_numeric_state(self.battery_soc_entity_id)

        self.backup_soc_percent_entry = self.get_config_entry_value(self.backup_soc_entry)
        self.charge_cutoff_soc_percent_entry = self.get_config_entry_value(self.charge_cutoff_soc_entry)

        self.total_energy_stored_kwh = (self.battery_soc_percent/100.0) * self.rated_capacity
        self.backup_buffer_kwh = (self.backup_soc_percent_entry/100.0) * self.rated_capacity
        self.stored_available_kwh = self.total_energy_stored_kwh - self.backup_buffer_kwh
        self.charge_unusable_kwh = (1-(self.charge_cutoff_soc_percent_entry/100.0)) * self.rated_capacity # kWh of buffer to 100% IE the charge limit

        self.kwh_till_full = self.rated_capacity - self.stored_available_kwh - self.charge_unusable_kwh

        self.battery_kw = self.get_safe_power_state(self.battery_power_entity_id)
        if(self.battery_power_sign_convention == "+ Charge, - Discharge"): # If battery power is the wrong way around, flip it
            self.battery_kw = -self.battery_kw
        elif(self.battery_power_sign_convention == "- Charge, + Discharge"):
            pass # Battery power is already in the correct convention
        else:
            raise ValueError(f"Invalid battery power sign convention '{self.battery_power_sign_convention}' in configuration! Must be either '- Charge, + Discharge' or '+ Charge, - Discharge'.")
        # Internal battery power convention ^^^^^^^:
        #   +kW = discharging (battery supplying power)
        #   -kW = charging (battery absorbing power)

        self.solar_kw = self.get_safe_power_state(self.solar_power_entity_id)
        self.grid_power = self.get_safe_power_state(self.grid_power_entity_id)
        if(self.grid_power_sign_convention == "- Import, + Export"):
            self.grid_power = -self.grid_power
        # Internal grid power convention (App expects):
        #   +kW = importing
        #   -kW = exporting

        self.solar_kw_remaining_today = self.get_safe_numeric_state(config_manager.solcast_solar_kwh_remaining_today_entity_id)
        self.load_power = self.get_safe_power_state(self.load_power_entity_id)

        self.avg_daily_load = sum(bin.avg_state*(self.time_step_minutes/60) for bin in self.get_load_avg(days_ago=self.load_avg_days))
        
        self.calculate_today_profit_cost()

    def set_export_limit_switch(self, state: bool = True) -> None:
        """Ensure the grid export limit switch is on to allow control."""
        switch_state = self.get_safe_state(self.grid_export_limit_switch_entity_id)
        if(switch_state['state'] != "on"):
            logger.debug(f"Grid export limit switch '{self.grid_export_limit_switch_entity_id}' is off, turning on to allow control.")
            self.ha.set_switch_state(self.grid_export_limit_switch_entity_id, state)
            time.sleep(2) # Allow time for HA to update

    def set_control_limits(self, control_mode: str, ems_limit: float, export_limit: float) -> None:
        """Set the control limits to the desired values."""

        self.set_export_limit_switch()
        # Scale internal kW values back to HA units (e.g. Watts) before sending
        ha_ems_limit = round(float(ems_limit) / self.power_scale_factor, 2)
        ha_export_limit = round(float(export_limit) / self.power_scale_factor, 2)

        self.ha.set_number(self.ems_power_limit_entity_id, ha_ems_limit)
        self.ha.set_number(self.export_limiter_entity_id, ha_export_limit)

        if(control_mode in self.control_mode_options):
            self.ha.set_select(self.ems_control_mode_entity_id, control_mode)
        else:
            raise ValueError(f"Requested control mode '{control_mode}' is not a valid control mode!")
    
    def check_control_limits(self, working_mode: str, control_mode: str, ems_limit: float, export_limit: float) -> None:
        """Check if control limits match desired values and change them if required."""

        current_control_mode = self.get_plant_mode()
        current_ems_limit = self.get_safe_power_state(self.ems_power_limit_entity_id)
        current_export_limit = self.get_safe_power_state(self.export_limiter_entity_id)
        

        wrong_control_mode = current_control_mode != control_mode
        wrong_ems_limit = abs(current_ems_limit - ems_limit) > 0.05
        wrong_export_limit = abs(current_export_limit - export_limit) > 0.05

        logger.debug(f"Checking control limits for working mode '{working_mode}': | "
                    f"Current Control Mode: {current_control_mode} (Desired: {control_mode}) | "
                    f"Current EMS Limit: {current_ems_limit} kW (Desired: {ems_limit} kW) | "
                    f"Current Export Limit: {current_export_limit} kW (Desired: {export_limit} kW) | "
                    f"Wrong Control Mode: {wrong_control_mode} | "
                    f"Wrong EMS Limit: {wrong_ems_limit} | "
                    f"Wrong Export Limit: {wrong_export_limit}"
        )

        any_limits_wrong = wrong_control_mode or wrong_ems_limit or wrong_export_limit

        if any_limits_wrong:          
            self.set_control_limits(control_mode, ems_limit, export_limit)
            logger.info(f"Changing control entities for mode: {working_mode}")
            time.sleep(5) # Allow time for HA to update
    
    def check_for_enabled_entities(self) -> None:
        """Checks to make sure all the entities needed for control are available and enabled, if not it raises an error."""
        # Map human-readable names to the configured entity IDs
        checks = {
            "EMS Control Mode": self.ems_control_mode_entity_id,
            "Battery SOC": self.battery_soc_entity_id,
            "Battery Power": self.battery_power_entity_id,
            "Solar Power": self.solar_power_entity_id,
            "Load Power": self.load_power_entity_id,
            "Grid Power": self.grid_power_entity_id,
            "Daily Import kWh": self.plant_daily_import_kwh_entity_id,
            "Daily Export kWh": self.plant_daily_export_kwh_entity_id,
            "Grid Export Switch": self.grid_export_limit_switch_entity_id,
            "Export Limiter": self.export_limiter_entity_id,
            "EMS Power Limit": self.ems_power_limit_entity_id
        }

        errors = []
        for name, eid in checks.items():
            if not eid:
                errors.append(f"- {name}: Configuration is empty")
                continue
            if self.is_numeric(eid):
                continue # If the entity ID is actually a numeric override value, skip the check to see if the entity exists in HA as it won't.
            try:
                self.get_safe_state(eid)
            except Exception:
                errors.append(f"- {name}: Entity '{eid}' is unavailable or does not exist")

        if errors:
            logger.error("The following required entities are missing or unavailable in Home Assistant:")
            for err in errors:
                logger.error(err)
            raise MPCEnergyError("One or more required Home Assistant entities are unavailable.")

    def system_curtailing(self, derate_allowance_kw=1.0, tolerance_kw=0.1) -> dict:
        """
        Return curtailment status and reason based on active limits.

        Battery SOC >= 97% is treated as a charging constraint because near-full
        batteries commonly trigger charge tapering/curtailment behaviour.
        """

        # control_mode = self.get_plant_mode()

        # inverter_limit_kw = self.get_safe_numeric_state(self.inverter_max_power_limit_entity_id)
        # charge_limit_kw = self.get_safe_numeric_state(self.battery_charge_limiter_entity_id)
        # pv_limit_kw = self.get_safe_numeric_state(self.pv_limiter_entity_id)
        # export_limit_kw = self.get_safe_numeric_state(self.export_limiter_entity_id)

        # charge_disabled_modes = {
        #     "Standby",
        #     "Command Discharging (PV First)",
        #     "Command Discharging (ESS First)",
        # }
        # high_soc_curtailment = self.battery_soc >= 97
        # charging_disabled = control_mode in charge_disabled_modes or high_soc_curtailment
        # effective_charge_limit_kw = 0 if charging_disabled else max(charge_limit_kw, 0)

        # ac_sink_limit_kw = max(self.load_power, 0) + max(export_limit_kw, 0)
        # configured_inverter_headroom_kw = min(max(inverter_limit_kw, 0), ac_sink_limit_kw)
        # derated_inverter_headroom_kw = min(max(inverter_limit_kw - derate_allowance_kw, 0), ac_sink_limit_kw)

        # configured_ceiling_kw = min(max(pv_limit_kw, 0), configured_inverter_headroom_kw + effective_charge_limit_kw)
        # derated_ceiling_kw = min(max(pv_limit_kw, 0), derated_inverter_headroom_kw + effective_charge_limit_kw)

        # curtailing_configured = self.solar_kw >= configured_ceiling_kw - tolerance_kw
        # curtailing_derated = self.solar_kw >= derated_ceiling_kw - tolerance_kw
        # curtailing = curtailing_configured or curtailing_derated

        # limiting_components = {
        #     "pv_limit": pv_limit_kw,
        #     "derated_inverter_limit": derated_inverter_headroom_kw + effective_charge_limit_kw,
        #     "ac_sink_limit": ac_sink_limit_kw + effective_charge_limit_kw,
        # }
        # limiting_reason = min(limiting_components, key=limiting_components.get)

        # reason_text_map = {
        #     "pv_limit": f"PV limit ({round(pv_limit_kw, 2)} kW)",
        #     "derated_inverter_limit": f"Inverter + Charge Limit ({round(derated_inverter_headroom_kw + effective_charge_limit_kw, 2)} kW)",
        #     "ac_sink_limit": f"Load + export sink limit ({round(ac_sink_limit_kw + effective_charge_limit_kw, 2)} kW)",
        # }

        # reason = reason_text_map[limiting_reason]
        # '''
        # if control_mode in charge_disabled_modes:
        #     reason_parts.append("battery charging disabled by mode")
        # if high_soc_curtailment:
        #     reason_parts.append(f"battery SOC high ({round(self.battery_soc, 1)}%)")'''

        curtailing = False
        reason = "Not Implemented Yet"

        return {
            "curtailing": curtailing,
            "reason": reason,
        }

    def historical_data(self, start_datetime=None, end_datetime=None, hours=None, bin_period=5) -> list[data_helpers.BinnedStateClass]:
        """
        Get the requested hours of historical data for the plant being (SOC, battery power, solar power, grid power, load power and prices.) in order oldest to newest
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

        battery_soc_state_history = self.ha.get_history(self.battery_soc_entity_id, start_time=start_datetime, end_time=end_datetime)
        battery_power_state_history = self.ha.get_history(self.battery_power_entity_id, start_time=start_datetime, end_time=end_datetime)
        for state in battery_power_state_history:
            try:
                val = float(state.state) * self.power_scale_factor
                if(self.battery_power_sign_convention == "+ Charge, - Discharge"):
                    val = -val
                state.state = val
            except:
                pass
        # Internal battery power convention ^^^^^^^:
        #   +kW = discharging (battery supplying power)
        #   -kW = charging (battery absorbing power)

        solar_power_state_history = self.ha.get_history(self.solar_power_entity_id, start_time=start_datetime, end_time=end_datetime)
        for state in solar_power_state_history:
            try:
                state.state = float(state.state) * self.power_scale_factor
            except:
                pass

        load_power_state_history = self.ha.get_history(self.load_power_entity_id, start_time=start_datetime, end_time=end_datetime)
        for state in load_power_state_history:
            try:
                state.state = float(state.state) * self.power_scale_factor
            except:
                pass

        grid_power_state_history = self.ha.get_history(self.grid_power_entity_id, start_time=start_datetime, end_time=end_datetime)
        for state in grid_power_state_history:
            try:
                val = float(state.state) * self.power_scale_factor
                if(self.grid_power_sign_convention == "- Import, + Export"):
                    val = -val
                state.state = val
            except:
                pass

        grid_import_kwh_state_history = self.ha.get_history(self.plant_daily_import_kwh_entity_id, start_time=start_datetime, end_time=end_datetime)
        grid_export_kwh_state_history = self.ha.get_history(self.plant_daily_export_kwh_entity_id, start_time=start_datetime, end_time=end_datetime)

        feed_in_state_history = self.ha.get_history("sensor.mpc_energy_manager_device_feed_in_price", start_time=start_datetime, end_time=end_datetime) 
        general_price_state_history = self.ha.get_history("sensor.mpc_energy_manager_device_general_price", start_time=start_datetime, end_time=end_datetime)
        working_mode_state_history = self.ha.get_history("sensor.mpc_energy_manager_device_working_mode", start_time=start_datetime, end_time=end_datetime, type=str)

        # Handle empty history for new systems
        if not battery_soc_state_history or not feed_in_state_history:
            logger.warning("Historical data is missing for one or more sensors. This is expected if the app was just installed.")
            return {
                "time_index": [], "soc": [], "battery_power": [], "inverter_power": [],
                "solar_power": [], "load_power": [], "grid_power": [], "prices_sell": [],
                "prices_buy": [], "plan_modes": [], "grid_import_kwh": [], "grid_export_kwh": []
            }

        binned_battery_soc_state_history = data_helpers.bin_data(battery_soc_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime)
        binned_battery_power_state_history = data_helpers.bin_data(battery_power_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime)
        binned_load_power_state_history = data_helpers.bin_data(load_power_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime)
        binned_solar_power_state_history = data_helpers.bin_data(solar_power_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime)
        binned_grid_power_state_history = data_helpers.bin_data(grid_power_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime)
        binned_grid_import_kwh_state_history = data_helpers.bin_data(grid_import_kwh_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime)
        binned_grid_export_kwh_state_history = data_helpers.bin_data(grid_export_kwh_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime)

        binned_feed_in_state_history = data_helpers.bin_data(feed_in_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime, interpolation_method="step")
        binned_general_price_state_history = data_helpers.bin_data(general_price_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime, interpolation_method="step")
        binned_working_mode_state_history = data_helpers.bin_data(working_mode_state_history, bin_period=bin_period, start_bin_datetime=start_datetime, end_bin_datetime=end_datetime, string_state=True)

        binned_battery_soc_kwh_history = [(item.avg_state / 100.0) * self.rated_capacity for item in binned_battery_soc_state_history]
        
        history_time_index = [item.time.isoformat() for item in binned_battery_soc_state_history] # Get the time marks from the data

        logger.debug(f"Received data bins span from {history_time_index[0]} to {history_time_index[-1]} ({len(history_time_index)} bins), request took {round(time.time()-start_timestamp,2)} seconds to retrieve and process.")

        output = {
            "time_index": history_time_index,
            "soc": binned_battery_soc_kwh_history,
            "battery_power": [state.avg_state for state in binned_battery_power_state_history],
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


    def dispatch(self, grid_export_limit=None):
        if(grid_export_limit == None):
            grid_export_limit = self.max_export_power
        else:
            grid_export_limit = min(max(grid_export_limit, 0), self.max_export_power)

        self.working_mode = self.ControlMode.DISPATCH
        self.check_control_limits(
            working_mode=self.working_mode,
            control_mode="Sell Power",
            ems_limit=self.max_inverter_power,
            export_limit=grid_export_limit
        )
        
    def export_all_solar(self):
        self.working_mode = self.ControlMode.EXPORT_ALL_SOLAR
        self.check_control_limits(
            working_mode=self.working_mode,
            control_mode="Discharge PV",
            ems_limit=0, # Battery Discharge Power
            export_limit=self.max_export_power
        )

    def export_excess_solar(self, battery_charge_limit=None):
        if(battery_charge_limit == None):
            battery_charge_limit = self.max_charge_power
        else:
            battery_charge_limit = min(max(battery_charge_limit, 0), self.max_charge_power)

        self.working_mode = self.ControlMode.EXPORT_EXCESS_SOLAR
        self.check_control_limits(
            working_mode=self.working_mode,
            control_mode="Auto",
            ems_limit=0, 
            export_limit=self.max_export_power
        )
        
    def solar_to_load(self):
        self.working_mode = self.ControlMode.SOLAR_TO_LOAD
        self.check_control_limits(
            working_mode=self.working_mode,
            control_mode="Auto",
            ems_limit=0, 
            export_limit=self.max_export_power
        )
        
    def import_power(self, battery_charge_limit = None, pv_limit = None, grid_import_limit = None):
        if(battery_charge_limit == None):
            battery_charge_limit = self.max_charge_power
        else:
            battery_charge_limit = min(max(battery_charge_limit, 0), self.max_charge_power)

        if(pv_limit == None):
            pv_limit = self.max_pv_power
        else:
            pv_limit = min(max(pv_limit, 0), self.max_pv_power)

        if(grid_import_limit == None):
            grid_import_limit = self.max_import_power
        else:
            grid_import_limit = min(max(grid_import_limit, 0), self.max_import_power)

        self.working_mode = self.ControlMode.GRID_IMPORT
        self.check_control_limits(
            working_mode=self.working_mode,
            control_mode="Import AC",
            ems_limit=battery_charge_limit, # Battery Charge Power
            export_limit=self.max_export_power
        )


    def self_consumption(self, pv_limit = None):
        if(pv_limit == None):
            pv_limit = self.max_pv_power
        self.working_mode = self.ControlMode.SELF_CONSUMPTION
        self.check_control_limits(
            working_mode=self.working_mode,
            control_mode="Auto",
            ems_limit=0,
            export_limit=self.max_export_power
        )
    
    def run(self):
        self.maintain_control_mode()

    def maintain_control_mode(self): # Maintain the current control mode (mainly export all solar)
        if(self.working_mode == self.ControlMode.EXPORT_ALL_SOLAR):
            self.export_all_solar()