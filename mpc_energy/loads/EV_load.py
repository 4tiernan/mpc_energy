from typing import Any, Tuple, List
from loads.optional_loads import OptionalLoad
import cvxpy as cp
import numpy as np
from datetime import datetime, timedelta
from mpc_logger import logger
import data_helpers

class EVLoad(OptionalLoad):
    EV_MODE_DISABLED = "Charging Disabled"
    EV_MODE_SOLAR_SMART = "Solar Smart"
    EV_MODE_READY_BY_TIME = "Ready by Time"
    EV_MODE_FORCE_ON = "Force On"

    def __init__(
        self,
        name: str,
        load_type: str,
        reward_cents_per_kwh: float,

        plugged_in_entity_id: str,
        power_entity_id: str,
        level_entity_id: str,
        capacity_kwh: float,
        min_level_limit: float,
        optimal_daily_min_soc: float,
        max_level_limit: float,
        charger_model: str,
        nominal_ac_voltage: float,
        min_charge_current: float,
        max_charge_current: float,
        charge_current_entity_id: str,
        charge_enable_entity_id: str,
        debias_load: bool
    ):
        # Optional load required params
        super().__init__(name, load_type, reward_cents_per_kwh, debias_load)
        
        # EV specific params
        self.plugged_in_entity_id = plugged_in_entity_id
        self.power_entity_id = power_entity_id
        self.level_entity_id = level_entity_id
        self.capacity_kwh = capacity_kwh
        self.min_level_limit = min_level_limit
        self.optimal_daily_min_soc = optimal_daily_min_soc
        self.max_level_limit = max_level_limit
        self.charger_model = charger_model
        self.nominal_ac_voltage = nominal_ac_voltage
        self.min_charge_current = min_charge_current
        self.max_charge_current = max_charge_current
        self.charge_current_entity_id = charge_current_entity_id
        self.charge_enable_entity_id = charge_enable_entity_id
        
        self.charger = None
        self.min_charge_power_kw = 0.0
        self.max_charge_power_kw = 0.0
        self.last_charge_mode = None

        logger.debug(f"Initialized EV Load '{name}' with capacity {capacity_kwh} kWh," 
                     f" current level limits {min_level_limit}% to {max_level_limit}%,"
                     f" Plugged-in entity: '{plugged_in_entity_id}', Power entity: '{power_entity_id}', Level entity: '{level_entity_id}'."
                     )

    def set_charger(self, charger):
        """Sets the specific EVCharger object and updates power limits."""
        self.charger = charger
        if self.charger:
            self.min_charge_power_kw = self.charger.min_charge_power_kw
            self.max_charge_power_kw = self.charger.max_charge_power_kw

    def setup_mqtt(self):
        """Creates the ha_mqtt entities required for this EV instance."""
        if self.ha_mqtt is None:
            return

        from ha_mqtt import CreateSelectInput
        
        # Instance-specific Charging Mode Selector
        self.ev_charging_mode_selector = CreateSelectInput(
            name=f"{self.name} Charging Mode",
            unique_id=f"ev_charging_mode_{self.name.lower().replace(' ', '_')}",
            options=[
                self.EV_MODE_DISABLED,
                self.EV_MODE_SOLAR_SMART,
                self.EV_MODE_READY_BY_TIME,
                self.EV_MODE_FORCE_ON,
            ]
        )
        self.ev_charging_mode_selector.set_state(self.EV_MODE_SOLAR_SMART)

        # Instance-specific Ready By Time Selector
        self.ready_by_time_selector = CreateSelectInput(
            name=f"{self.name} Ready By Time",
            unique_id=f"ev_ready_by_time_{self.name.lower().replace(' ', '_')}",
            options=[
                "NA", "00:00", "00:30", "01:00", "01:30", "02:00", "02:30",
                "03:00", "03:30", "04:00", "04:30", "05:00", "05:30",
                "06:00", "06:30", "07:00", "07:30", "08:00", "08:30",
                "09:00", "09:30", "10:00", "10:30", "11:00", "11:30",
                "12:00", "12:30", "13:00", "13:30", "14:00", "14:30",
                "15:00", "15:30", "16:00", "16:30", "17:00", "17:30",
                "18:00", "18:30", "19:00", "19:30", "20:00", "20:30",
                "21:00", "21:30", "22:00", "22:30", "23:00", "23:30"
            ]
        )
        self.ready_by_time_selector.set_state("NA")

    def settings_changed(self) -> bool:
        """Detects if EV settings have changed via MQTT selectors."""
        if not hasattr(self, "ev_charging_mode_selector"):
            return False
            
        current_mode = self.ev_charging_mode_selector.state
        current_time = self.ready_by_time_selector.state
        
        if not hasattr(self, "_last_mqtt_mode"):
            self._last_mqtt_mode = current_mode
            self._last_mqtt_time = current_time
            return False
            
        changed = False
        if current_mode != self._last_mqtt_mode or current_time != self._last_mqtt_time:
            self._last_mqtt_mode = current_mode
            self._last_mqtt_time = current_time
            changed = True
            
        if current_mode != self.EV_MODE_READY_BY_TIME and current_time != "NA":
            self.ready_by_time_selector.set_state("NA")
            
        return changed

    def build_cvxpy(self, mpc):
        self.ev_charge_48hr_reward = np.zeros(int(mpc.N_5min), dtype=float)
        self.ev_charge_48hr_reward[:int(mpc.steps_per_hr*48)] = self.reward_cents_per_kwh / 100.0 # Only reward EV charging in the first 48 hrs to avoid charging near the end of the forecast horizon.

        divisor = max(int(mpc.N_5min) * mpc.dt_5min * (self.capacity_kwh), 1.0)
        self.charge_maintain_reward = 0.20 / divisor # The numerator is the total reward we want to provide for maintaining charge over the entire forecast horizon

        n = int(mpc.N_5min)
        self.p_ev = cp.Variable(n, nonneg=True, name=f"{self.name}_p_ev")
        self.ev_soc = cp.Variable(n + 1, name=f"{self.name}_ev_soc")
        self.unachievable_kwh = cp.Variable(n, nonneg=True, name=f"{self.name}_unachievable_kwh")
        
        self.p_max_param = cp.Parameter(n, nonneg=True, name=f"{self.name}_p_max_param")
        self.soc_init_param = cp.Parameter(nonneg=True, name=f"{self.name}_soc_init_param")
        self.soc_upper_limit_param = cp.Parameter(nonneg=True, name=f"{self.name}_soc_upper_limit_param")
        self.soc_min_required_param = cp.Parameter(n, nonneg=True, name=f"{self.name}_soc_min_required_param")
        self.soc_optimal_min_param = cp.Parameter(n, nonneg=True, name=f"{self.name}_soc_optimal_min_param")
        self.draw_forecast_param = cp.Parameter(n, name=f"{self.name}_draw_forecast")

        constraints = [
            self.ev_soc[0] == self.soc_init_param,
            self.ev_soc[1:] == self.ev_soc[:-1] + (mpc.dt_5min * self.p_ev) - (mpc.dt_5min * self.draw_forecast_param),
            self.ev_soc[1:] >= 0,
            self.ev_soc[1:] <= self.soc_upper_limit_param,
            self.ev_soc[1:] >= self.soc_min_required_param - self.unachievable_kwh, # Allow for some unachievable kWh to ensure feasibility if targets can't be met
            self.ev_soc[1:] >= self.soc_optimal_min_param - self.unachievable_kwh,
            self.p_ev >= 0,
            self.p_ev <= self.p_max_param
        ]

        objective_term = (
            - cp.sum(cp.multiply(self.ev_charge_48hr_reward, self.p_ev)) * mpc.dt_5min
            - cp.sum(cp.multiply(self.charge_maintain_reward, self.ev_soc[0:-1])) * mpc.dt_5min
            + cp.sum(self.unachievable_kwh) * 10000.0  # Large penalty for missing targets
        )

        return constraints, objective_term, self.p_ev
    
    def _normalise_ev_mode(self):
        mode = self.EV_MODE_SOLAR_SMART
        if hasattr(self, "ev_charging_mode_selector"):
            selected_mode = self.ev_charging_mode_selector.state
            if(selected_mode is not None and str(selected_mode).strip() != ""):
                mode = str(selected_mode).strip()
        allowed_modes = {
            self.EV_MODE_DISABLED,
            self.EV_MODE_SOLAR_SMART,
            self.EV_MODE_READY_BY_TIME,
            self.EV_MODE_FORCE_ON,
        }
        if(mode not in allowed_modes):
            logger.warning(f"Unknown EV charging mode '{mode}', defaulting to '{self.EV_MODE_SOLAR_SMART}'.")
            mode = self.EV_MODE_SOLAR_SMART
        return mode
    
    def update_mpc_values(self, mpc, time_index):
        self.update_data()

        # Mode detection via HA MQTT
        mode = self._normalise_ev_mode()

        if mode == self.EV_MODE_DISABLED:
            n = int(mpc.N_5min)
            self.p_max_param.value = np.zeros(n, dtype=float)
            self.soc_init_param.value = float(self.current_ev_soc_kWh or 0.0)
            self.soc_upper_limit_param.value = max(float((self.max_level_limit / 100.0) * self.capacity_kwh), float(self.current_ev_soc_kWh or 0.0))
            self.soc_min_required_param.value = np.zeros(n, dtype=float)
            self.soc_optimal_min_param.value = np.zeros(n, dtype=float)
            return

        # Build power limits
        p_max_arr = np.zeros(int(mpc.N_5min), dtype=float) # Start with no charging allowed, then enable based on mode and grid import limits
        grid_import_limit = mpc.grid_import_limit
        
        for i, load in enumerate(mpc.load_5min):
            max_avail = grid_import_limit - load
            p_max_arr[i] = max(0.0, min(self.max_charge_power_kw, max_avail))
        
        # If the EV is not connected, constrain the first and second charge power steps to zero.
        # This allows future planning if it's plugged in later, but prevents immediate commands.
        if not self.is_plugged_in:
            if len(p_max_arr) > 0: p_max_arr[0] = 0.0
            if len(p_max_arr) > 1: p_max_arr[1] = 0.0
            logger.debug(f"EV '{self.name}' is not currently plugged in. Constraining immediate charge power to 0 kW until next update.")

        # Background Degradation (Phantom Drain)
        # Convert SOC% delta to Power (kW): P = -deltaSOC * Capacity * (60/5) / 100
        soc_delta_forecast = self.forecast_level_delta(time_index)
        draw_forecast = -soc_delta_forecast * self.capacity_kwh * 0.12
        self.draw_forecast_param.value = draw_forecast
        
        logger.debug(f"EVLoad '{self.name}' phantom drain forecast: avg={np.mean(draw_forecast)*1000:.1f}W")
        

        self.min_target_kwh = (self.min_level_limit / 100.0) * self.capacity_kwh
        self.optimal_min_kwh = (self.optimal_daily_min_soc / 100.0) * self.capacity_kwh
        self.max_target_kwh = (self.max_level_limit / 100.0) * self.capacity_kwh

        # SOC constraints
        ev_soc_min_required_arr = np.ones(int(mpc.N_5min), dtype=float) * self.min_target_kwh
        ev_soc_optimal_min_arr = np.zeros(int(mpc.N_5min), dtype=float)

        # If the EV soc is below the minimum soc target, charge asap reguardless of the selected mode. 
        if(self.current_ev_soc_kWh is not None and self.current_ev_soc_kWh < self.min_target_kwh):
            logger.debug(f"EV SOC of {self.current_ev_soc_kWh:.2f} kWh is below the minimum SOC target of {self.min_target_kwh:.2f} kWh. The MPC will attempt to charge the EV as soon as possible to reach the minimum SOC target.")
            ev_soc_min_required_arr = self.build_ev_min_soc_constraint(target_soc=self.min_target_kwh, p_max_arr=p_max_arr, mpc=mpc)
        else:
            if(mode == self.EV_MODE_SOLAR_SMART):
                pass # No minimum SOC constraint, let the optimiser decide when to charge based on the solar forecast and prices.
            elif(mode == self.EV_MODE_READY_BY_TIME):
                ev_soc_min_required_arr = self.build_ev_ready_by_time_min_soc_mask(time_index, mpc)
            elif(mode == self.EV_MODE_FORCE_ON):
                ev_soc_min_required_arr = self.build_ev_min_soc_constraint(target_soc=self.max_target_kwh, p_max_arr=p_max_arr, mpc=mpc)
                logger.debug("EV Force On Mode Active. required SOC array: " + str(ev_soc_min_required_arr))
            else:
                logger.warning(f"Unknown EV charging mode '{mode}', defaulting to 'Solar Smart' (no minimum SOC constraint).")

        # Apply Optimal Daily Min (Target by EOD)
        if self.optimal_daily_min_soc > 0 and self.optimal_min_kwh > self.current_ev_soc_kWh: 
            ev_soc_optimal_min_arr = self.build_ev_optimal_daily_min_mask(time_index, mpc)
        
        self.p_max_param.value = p_max_arr
        self.soc_init_param.value = float(self.current_ev_soc_kWh or 0.0)
        # Ensure upper limit is at least as high as current SOC to prevent solver infeasibility if car is over-charged
        self.soc_upper_limit_param.value = max(float((self.max_level_limit / 100.0) * self.capacity_kwh), float(self.current_ev_soc_kWh or 0.0))
        self.soc_min_required_param.value = ev_soc_min_required_arr # Set the minimum SOC constraint array based on the selected mode and current SOC
        self.soc_optimal_min_param.value = ev_soc_optimal_min_arr
        
    def update_data(self) -> None:
        """Collects and updates real-time data from Home Assistant."""
        self.current_ev_soc_percent = self.ha.get_numeric_state(self.level_entity_id) if self.level_entity_id else None
        if self.current_ev_soc_percent is not None:
            self.current_ev_soc_kWh = (self.current_ev_soc_percent / 100.0) * self.capacity_kwh
        else:
            self.current_ev_soc_kWh = None
        
        if self.charger:
            self.charger.update_state()
            self.min_charge_power_kw = self.charger.min_charge_power_kw
            self.max_charge_power_kw = self.charger.max_charge_power_kw
            self.is_plugged_in = getattr(self.charger, 'car_plugged_in', True)
        else:
            if self.plugged_in_entity_id:
                self.is_plugged_in = self.ha.get_boolean_state(self.plugged_in_entity_id)
            else:
                self.is_plugged_in = True  # Assume always plugged in if no sensor provided

    def build_ev_min_soc_constraint(self, target_soc, p_max_arr, mpc):
        target_soc = max(min(target_soc, self.capacity_kwh), 0.0)
        ev_soc_min_required_arr = [min(self.current_ev_soc_kWh + i*p_max_arr[i]*0.95 * mpc.dt_5min, target_soc) for i in range(int(mpc.N_5min))] *np.ones(int(mpc.N_5min), dtype=float) # Force minimum SOC constraint based on max charge rate but allow a slight reductuion to ensure feasibility
        return ev_soc_min_required_arr
    
    def build_ev_ready_by_time_min_soc_mask(self, time_index, mpc):
        self.ev_full_by_time = self.ready_by_time_selector.state if hasattr(self, "ready_by_time_selector") else self.ev_full_by_time

        required_mask = np.zeros(int(mpc.N_5min), dtype=float)
        if(self.capacity_kwh <= 0):
            return required_mask

        try:
            full_hour, full_minute = [int(v) for v in self.ev_full_by_time.split(":")]
            target_clock = datetime.now(self.local_tz).replace(
                hour=full_hour,
                minute=full_minute,
                second=0,
                microsecond=0,
            )
        except Exception:
            logger.warning(f"Invalid ev_full_by_time '{self.ev_full_by_time}'. Expected HH:MM, defaulting to 07:00.")
            target_clock = datetime.now(self.local_tz).replace(hour=7, minute=0, second=0, microsecond=0)

        if(target_clock < mpc.sim_start):
            target_clock = target_clock + timedelta(days=1)

        hours_until_target = (target_clock - mpc.sim_start).total_seconds() / 3600
        energy_needed = self.max_target_kwh - self.current_ev_soc_kWh
        charge_duration_at_max_rate = energy_needed / self.max_charge_power_kw if self.max_charge_power_kw > 0 else float('inf')
        logger.debug(f"EV charge-by time: {target_clock.strftime('%Y-%m-%d %H:%M')}, which is {hours_until_target:.2f} hours from sim start. Energy needed: {energy_needed:.2f} kWh, Charge duration at max rate: {charge_duration_at_max_rate:.2f} hours.")
        if(hours_until_target < charge_duration_at_max_rate):
            logger.warning(f"Target ready-by time of {target_clock.strftime('%H:%M')} is only {hours_until_target:.2f} hours away, which is less than the {charge_duration_at_max_rate:.2f} hours required to fully charge the EV at max rate. The MPC will attempt to charge as much as possible by the target time, but may not reach full charge.")
            target_clock = target_clock + timedelta(hours=charge_duration_at_max_rate - hours_until_target) # Adjust the target clock to account for the time needed to charge

        hold_end = target_clock + timedelta(hours=1)
        for idx, step_time in enumerate(time_index):
            if(target_clock <= step_time <= hold_end):
                required_mask[idx] = self.max_target_kwh

        return required_mask

    def build_ev_optimal_daily_min_mask(self, time_index, mpc):
        """Encourages hitting the Optimal Daily Min SOC by 10 PM each day."""
        required_mask = np.zeros(int(mpc.N_5min), dtype=float)
        if self.capacity_kwh <= 0 or self.optimal_daily_min_soc <= 0:
            return required_mask

        target_kwh = (self.optimal_daily_min_soc / 100.0) * self.capacity_kwh

        achieve_optimal_by_index = 48 * mpc.steps_per_hr

        required_mask[achieve_optimal_by_index] = target_kwh
        logger.debug(f"Optimal Daily Min SOC constraint set to {target_kwh:.2f} kWh at index {achieve_optimal_by_index}") 

        # for idx, step_time in enumerate(time_index):
        #     # Check for 10 PM (EOD)
        #     if step_time.hour == 22 and 0 <= step_time.minute <= 59:
        #         # Only apply if it doesn't conflict with a higher critical SOC requirement
        #         required_mask[idx] = target_kwh

        return required_mask

    def get_results(self, dt):
        p_ev = self.p_ev.value
        soc_ev = self.ev_soc.value
        if p_ev is None: return {}

        p_res = [round(float(x), 2) for x in p_ev.tolist()]
        if self.min_charge_power_kw > 0:
            for i, p in enumerate(p_res):
                if 0.05 < p < self.min_charge_power_kw:
                    p_res[i] = 0.0
        
        self.target_charge_rate = p_res[0]
        soc_pct = [round((x / self.capacity_kwh) * 100, 2) if self.capacity_kwh > 0 else 0 for x in soc_ev.tolist()]

        if(self._normalise_ev_mode() == self.EV_MODE_FORCE_ON and self.is_plugged_in):
            self.target_charge_rate = self.max_charge_power_kw

        if(soc_pct[0] >= self.max_level_limit-5):
            self.target_charge_rate = self.min_charge_power_kw # If the EV battery is at its maximum, keep it there. 

        if(self._normalise_ev_mode() == self.EV_MODE_DISABLED and self.last_charge_mode != self.EV_MODE_DISABLED):
            self.charger.set_target_charge_rate(0.0, None) # Set charge rate to 0 immediately when switching to disabled mode to ensure the charger stops charging as soon as possible.

        self.charger.set_target_charge_rate(self.target_charge_rate, self._normalise_ev_mode()) # Update the charger with the new target charge rate for real-time control

        # Update the last charge mode
        self.last_charge_mode = self._normalise_ev_mode()

        return {
            "power": p_res,
            "raw_power": p_ev.tolist(),
            "soc_percent": soc_pct
        }
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "load_type": self.load_type,
            "reward_cents_per_kwh": self.reward_cents_per_kwh,

            "plugged_in_entity_id": self.plugged_in_entity_id,
            "power_entity_id": self.power_entity_id,
            "level_entity_id": self.level_entity_id,
            "capacity_kwh": self.capacity_kwh,
            "min_level_limit": self.min_level_limit,
            "optimal_daily_min_soc": self.optimal_daily_min_soc,
            "max_level_limit": self.max_level_limit,
            "charger_model": self.charger_model,
            "nominal_ac_voltage": self.nominal_ac_voltage,
            "min_charge_current": self.min_charge_current,
            "max_charge_current": self.max_charge_current,
            "charge_current_entity_id": self.charge_current_entity_id,
            "charge_enable_entity_id": self.charge_enable_entity_id,
            "three_phase_available_entity_id": getattr(self.charger, 'three_phase_available_entity_id', None) if self.charger else None,
            "three_phase_available": getattr(self.charger, 'three_phase_available', None) if self.charger else None,
            "debias_load": self.debias_load 
        }

    @classmethod
    def from_dict(cls, item: dict[str, Any]) -> "EVLoad | None":  
        """
        Base from_dict. If called on OptionalLoad, acts as a factory. 
        If called on a subclass, instantiates that subclass.
        """
        if not item:
            return None

        return cls(
            name=str(item.get("name", "")).strip(),
            load_type=str(item.get("load_type", "ev")).strip(),
            reward_cents_per_kwh=float(item.get("reward_cents_per_kwh", 0.0) or 0.0),

            plugged_in_entity_id=str(item.get("plugged_in_entity_id", "")).strip(),
            power_entity_id=str(item.get("power_entity_id", "")).strip(),
            level_entity_id=str(item.get("level_entity_id", "")).strip(),
            capacity_kwh=float(item.get("capacity_kwh", 0.0) or 0.0),
            min_level_limit=float(item.get("min_level_limit", 0.0) or 0.0),
            optimal_daily_min_soc=float(item.get("optimal_daily_min_soc", 0.0) or 0.0),
            max_level_limit=float(item.get("max_level_limit", 100.0) or 100.0),
            charger_model=str(item.get("charger_model", "Generic")).strip(),
            nominal_ac_voltage=float(item.get("nominal_ac_voltage", 230.0) or 230.0),
            min_charge_current=float(item.get("min_charge_current", 0.0) or 0.0),
            max_charge_current=float(item.get("max_charge_current", 0.0) or 0.0),
            charge_current_entity_id=str(item.get("charge_current_entity_id", "")).strip(),
            charge_enable_entity_id=str(item.get("charge_enable_entity_id", "")).strip(),
            #three_phase_available_entity_id=str(item.get("three_phase_available_entity_id", "")).strip(),
            #three_phase_available=bool(item.get("three_phase_available", False)),
            debias_load=bool(item.get("debias_load", True))
        )
    
