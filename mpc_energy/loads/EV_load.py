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
        max_charge_power_kw: float,
        min_charge_power_kw: float, 
        power_entity_id: str,
        level_entity_id: str,
        capacity_kwh: float,
        min_level_limit: float,
        max_level_limit: float,
    ):
        # EV specific params
        self.plugged_in_entity_id = plugged_in_entity_id
        self.max_charge_power_kw = max_charge_power_kw
        self.min_charge_power_kw = min_charge_power_kw
        self.power_entity_id = power_entity_id
        self.level_entity_id = level_entity_id
        self.capacity_kwh = capacity_kwh
        self.min_level_limit = min_level_limit
        self.max_level_limit = max_level_limit

        logger.debug(f"Initialized EV Load '{name}' with capacity {capacity_kwh} kWh," 
                     f" current level limits {min_level_limit}% to {max_level_limit}%,"
                     f"max charge power {max_charge_power_kw} kW,"
                     f"min charge power {min_charge_power_kw} kW, and reward {reward_cents_per_kwh} c/kWh."
                     f" Plugged-in entity: '{plugged_in_entity_id}', Power entity: '{power_entity_id}', Level entity: '{level_entity_id}'."
                     )

        # Optional load required params
        super().__init__(name, load_type, reward_cents_per_kwh)
    
    def get_historical_power(self, start=None, end=None, hours=None, bin_period=5):
        if not self.power_entity_id: return None
        
        if hours is not None and (start is None or end is None):
            start, end = data_helpers.get_time_range_from_hours(hours, self.local_tz)

        history = self.ha.get_history(self.power_entity_id, start_time=start, end_time=end)
        #logger.debug(f"Raw history for EV load '{self.name}' (entity '{self.power_entity_id}') from {start} to {end}: {history}")
        if not history: return None
        
        requested_seconds = max((end - start).total_seconds(), 1.0)
        if len(history) == 1:
            # If there's only one point and it covers the start of our window, it spans the whole duration
            ev_span_seconds = requested_seconds if history[0].time <= start + timedelta(minutes=5) else 0.0
        else:
            ev_span_seconds = max((history[-1].time - history[0].time).total_seconds(), 0.0)
        coverage = ev_span_seconds / requested_seconds
        
        if coverage < 0.5:
            logger.warning(f"Insufficient history coverage ({round(coverage*100)}%) for EV load {self.name} with power entity '{self.power_entity_id}'. Skipping debias.")
            return None
            
        binned = data_helpers.bin_data(history, bin_period, start, end, interpolation_method="step")
        return binned

    def build_cvxpy(self, mpc):
        self.ev_charge_48hr_reward = np.zeros(int(mpc.N_5min), dtype=float)
        self.ev_charge_48hr_reward[:int(mpc.steps_per_hr*48)] = self.reward_cents_per_kwh / 100.0 # Only reward EV charging in the first 48 hrs to avoid charging near the end of the forecast horizon.

        divisor = max(int(mpc.N_5min) * mpc.dt_5min * (self.capacity_kwh), 1.0)
        self.charge_maintain_reward = 0.20 / divisor

        n = int(mpc.N_5min)
        self.p_ev = cp.Variable(n, nonneg=True, name=f"{self.name}_p_ev")
        self.ev_soc = cp.Variable(n + 1, name=f"{self.name}_ev_soc")
        
        self.p_max_param = cp.Parameter(n, nonneg=True, name=f"{self.name}_p_max_param")
        self.soc_init_param = cp.Parameter(nonneg=True, name=f"{self.name}_soc_init_param")
        self.soc_upper_limit_param = cp.Parameter(nonneg=True, name=f"{self.name}_soc_upper_limit_param")
        self.soc_min_required_param = cp.Parameter(n, nonneg=True, name=f"{self.name}_soc_min_required_param")

        constraints = [
            self.ev_soc[0] == self.soc_init_param,
            self.ev_soc[1:] == self.ev_soc[:-1] + (mpc.dt_5min * self.p_ev),
            self.ev_soc[1:] >= 0,
            self.ev_soc[1:] <= self.soc_upper_limit_param,
            self.ev_soc[1:] >= self.soc_min_required_param, # List of minimum SOC values
            self.p_ev >= 0,
            self.p_ev <= self.p_max_param,
            mpc.soc[1:] >= self.p_ev * mpc.dt_5min + mpc.soc_min_param
        ]

        objective_term = (
            - cp.sum(cp.multiply(self.ev_charge_48hr_reward, self.p_ev)) * mpc.dt_5min
            - cp.sum(cp.multiply(self.charge_maintain_reward, self.ev_soc[0:-1])) * mpc.dt_5min
        )

        return constraints, objective_term, self.p_ev
    
    def _normalise_ev_mode(self):
        mode = self.EV_MODE_SOLAR_SMART
        if(self.ha_mqtt is not None and hasattr(self.ha_mqtt, "ev_charging_mode_selector")):
            selected_mode = self.ha_mqtt.ev_charging_mode_selector.state
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

        # Build power limits
        p_max_arr = np.zeros(int(mpc.N_5min), dtype=float) # Start with no charging allowed, then enable based on mode and grid import limits
        grid_import_limit = mpc.grid_import_limit
        
        for i, load in enumerate(mpc.load_5min):
            max_avail = grid_import_limit - load
            p_max_arr[i] = max(0.0, min(self.max_charge_power_kw, max_avail))
        

        # SOC constraints
        ev_soc_min_required_arr = np.zeros(int(mpc.N_5min), dtype=float)
        self.min_target_kwh = (self.min_level_limit / 100.0) * self.capacity_kwh
        self.max_target_kwh = (self.max_level_limit / 100.0) * self.capacity_kwh

        # If the EV soc is below the minimum soc target, charge asap reguardless of the selected mode. 
        if(self.current_ev_soc_kWh < self.min_target_kwh):
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
            elif(mode == self.EV_MODE_DISABLED):  # Charging Disabled
                p_max_arr = np.zeros(int(mpc.N_5min), dtype=float) # No charging allowed, set max power to 0
            else:
                logger.warning(f"Unknown EV charging mode '{mode}', defaulting to 'Solar Smart' (no minimum SOC constraint).")
                # No minimum SOC constraint, let the optimiser decide when to charge based on the solar forecast and prices.
        
        self.p_max_param.value = p_max_arr
        self.soc_init_param.value = float(self.current_ev_soc_kWh)
        self.soc_upper_limit_param.value = max(float((self.max_level_limit / 100.0) * self.capacity_kwh), 0) # Set the upper SOC limit based on the max_level_limit percentage
        self.soc_min_required_param.value = ev_soc_min_required_arr # Set the minimum SOC constraint array based on the selected mode and current SOC
        
    def update_data(self) -> None:
        """Collects and updates real-time data from Home Assistant."""
        self.current_ev_soc_percent = self.ha.get_numeric_state(self.level_entity_id) if self.level_entity_id else None
        if self.current_ev_soc_percent is not None:
            self.current_ev_soc_kWh = (self.current_ev_soc_percent / 100.0) * self.capacity_kwh
        else:
            self.current_ev_soc_kWh = None
        
        if self.plugged_in_entity_id:
            self.is_plugged_in = self.ha.get_boolean_state(self.plugged_in_entity_id)
        else:
            self.is_plugged_in = True  # Assume always plugged in if no sensor provided
            
    def build_ev_min_soc_constraint(self, target_soc, p_max_arr, mpc):
        target_soc = max(min(target_soc, self.capacity_kwh), 0.0)
        ev_soc_min_required_arr = [min(self.current_ev_soc_kWh + i*p_max_arr[i]*0.95 * mpc.dt_5min, target_soc) for i in range(int(mpc.N_5min))] *np.ones(int(mpc.N_5min), dtype=float) # Force minimum SOC constraint based on max charge rate but allow a slight reductuion to ensure feasibility
        return ev_soc_min_required_arr
    
    def build_ev_ready_by_time_min_soc_mask(self, time_index, mpc):
        self.ev_full_by_time = self.ha_mqtt.ready_by_time_selector.state if (self.ha_mqtt is not None and hasattr(self.ha_mqtt, "ready_by_time_selector")) else self.ev_full_by_time

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
        
        return {
            "ev_charging_power": p_res,
            "ev_soc_percent": soc_pct,
            "power": p_res
        }
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "load_type": self.load_type,
            "reward_cents_per_kwh": self.reward_cents_per_kwh,

            "plugged_in_entity_id": self.plugged_in_entity_id,
            "max_charge_power_kw": self.max_charge_power_kw,
            "min_charge_power_kw": self.min_charge_power_kw,
            "power_entity_id": self.power_entity_id,
            "level_entity_id": self.level_entity_id,
            "capacity_kwh": self.capacity_kwh,
            "min_level_limit": self.min_level_limit,
            "max_level_limit": self.max_level_limit,
            
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
            max_charge_power_kw=float(item.get("max_charge_power_kw", 0.0) or 0.0),
            min_charge_power_kw=float(item.get("min_charge_power_kw", 0.0) or 0.0),
            power_entity_id=str(item.get("power_entity_id", "")).strip(),
            level_entity_id=str(item.get("level_entity_id", "")).strip(),
            capacity_kwh=float(item.get("capacity_kwh", 0.0) or 0.0),
            min_level_limit=float(item.get("min_level_limit", 0.0) or 0.0),
            max_level_limit=float(item.get("max_level_limit", 100.0) or 100.0),
        )
    
