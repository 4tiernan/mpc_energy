from typing import Any, List, Tuple, Dict
from loads.optional_loads import OptionalLoad
import cvxpy as cp
import numpy as np
from mpc_logger import logger
import datetime
import data_helpers
from collections import defaultdict

class HWLoad(OptionalLoad):
    """
    Specialized load for Hot Water systems.
    Converts temperature and volume into energy (kWh) and percentage level.
    """
    def __init__(
        self,
        name: str,
        load_type: str,
        reward_cents_per_kwh: float,
        debias_load: bool,
        volume_l: float,
        temp_min: float,
        temp_max: float,
        power_entity_id: str = "",
        max_charge_power_entity_id: str = "",
        plugged_in_entity_id: str = "",
        level_entity_id: str = "",
        hw_power_unit_scale: str = "kW"
    ):
        super().__init__(name, load_type, reward_cents_per_kwh, debias_load)
        self.volume_l = float(volume_l)
        self.temp_min = float(temp_min)
        self.temp_max = float(temp_max)
        self.power_entity_id = power_entity_id
        self.max_charge_power_entity_id = max_charge_power_entity_id
        self.plugged_in_entity_id = plugged_in_entity_id
        self.level_entity_id = level_entity_id
        self.hw_power_unit_scale = hw_power_unit_scale
        self.power_scale_factor = 0.001 if self.hw_power_unit_scale == "W" else 1.0

        # Internal state
        self.current_power_kw = 0.0
        self.max_charge_power_limit = 0.0
        self.is_plugged_in = False
        self.capacity_kwh = 0.0
        self.current_level_percent = 0.0
        self.current_charge_kwh = 0.0

        # Forecast cache
        self.load_avg_days = 3
        self.avg_draw_day = None
        self.last_draw_data_retrival_timestamp = 0

        logger.debug(f"Initialized HWLoad '{self.name}' with scale={self.hw_power_unit_scale}, volume={self.volume_l}L, temp_min={self.temp_min}°C, temp_max={self.temp_max}°C, power_entity_id='{self.power_entity_id}', max_charge_power_entity_id='{self.max_charge_power_entity_id}', plugged_in_entity_id='{self.plugged_in_entity_id}', level_entity_id='{self.level_entity_id}'")

    def update_data(self) -> None:
        ha = self.ha
        def get_val(eid, default=0.0):
            if not eid: return float(default)
            try:
                # If the UI entry is a raw number (kW), don't apply scaling
                return float(eid)
            except (ValueError, TypeError):
                # If it's an entity ID, fetch and scale to kW
                return ha.get_numeric_state(eid) * self.power_scale_factor

        # Update basic power and plugged-in status
        self.current_power_kw = get_val(self.power_entity_id, 0.0)
        self.max_charge_power_limit = get_val(self.max_charge_power_entity_id, 3.6)
        self.is_plugged_in = ha.get_boolean_state(self.plugged_in_entity_id) if self.plugged_in_entity_id else True

        # Thermal to Energy Conversion
        raw_temp = ha.get_numeric_state(self.level_entity_id) if self.level_entity_id else 0.0
        
        if self.volume_l > 0 and self.temp_max > self.temp_min:
            # Energy Capacity (kWh) = (Volume * 4.186 * deltaT) / 3600
            self.capacity_kwh = (self.volume_l * 4.186 * (self.temp_max - self.temp_min)) / 3600.0
            # Calculate level based on current temperature: % = (current_T - T_min) / (T_max - T_min)
            self.current_level_percent = min(max((raw_temp - self.temp_min) / (self.temp_max - self.temp_min) * 100.0, 0.0), 100.0)
            self.current_charge_kwh = (self.current_level_percent / 100.0) * self.capacity_kwh
        else:
            self.current_level_percent = 0.0 

    def get_historical_power(self, start=None, end=None, hours=None, bin_period=5):
        """Retrieve and bin historical power usage for this device, applying scale factor."""
        binned = super().get_historical_power(start, end, hours, bin_period)
        if binned and self.power_scale_factor != 1.0:
            for b in binned:
                if b.avg_state is not None:
                    b.avg_state *= self.power_scale_factor
        return binned

    def build_cvxpy(self, mpc):
        n = mpc.N_5min
        dt = mpc.dt_5min
        mpc_soc = mpc.soc
        mpc_soc_min_param = mpc.soc_min_param

        self.p_hw = cp.Variable(n, nonneg=True)
        self.hw_energy = cp.Variable(n + 1)
        
        self.soc_init_param = cp.Parameter(nonneg=True)
        self.draw_forecast_param = cp.Parameter(n, nonneg=True)
        self.p_max_limit_param = cp.Parameter(nonneg=True)
        
        constraints = [
            self.hw_energy[0] == self.soc_init_param,
            self.hw_energy[1:] == self.hw_energy[:-1] + (self.p_hw * dt) - (self.draw_forecast_param * dt),
            self.hw_energy >= 0,
            self.hw_energy <= self.capacity_kwh,
            self.p_hw <= self.p_max_limit_param,
            mpc_soc[1:] >= self.p_hw * dt + mpc_soc_min_param
        ]
        
        # Maintenance reward: Tiny incentive to keep the tank full
        # User reward: Incentivize heating when prices are low or solar is excess
        objective_term = - (self.reward_cents_per_kwh * cp.sum(self.p_hw) * dt)
        
        return constraints, objective_term, self.p_hw

    def update_mpc_values(self, mpc, time_index):
        self.update_data()
        n = mpc.N_5min
        
        self.soc_init_param.value = float(self.current_charge_kwh)
        self.p_max_limit_param.value = float(self.max_charge_power_limit or 3.6)
        
        # Model draw (usage + losses) based on historical average
        self.draw_forecast_param.value = self.forecast_draw_power(time_index)

    def get_draw_avg(self, days_ago=None, hours_update_interval=24):
        """Calculate the average thermal draw (losses + usage) profile for a day."""
        if days_ago is None:
            days_ago = self.load_avg_days

        now_ts = datetime.datetime.now().timestamp()
        if (self.avg_draw_day is not None and 
            now_ts - self.last_draw_data_retrival_timestamp < hours_update_interval * 3600):
            return self.avg_draw_day

        bin_period = 5
        now = datetime.datetime.now(self.local_tz)
        rounded_now = data_helpers.round_minutes(now, bin_period)
        start = rounded_now - datetime.timedelta(days=days_ago)

        h_power = self.ha.get_history(self.power_entity_id, start_time=start, end_time=rounded_now)
        if self.power_scale_factor != 1.0:
            for s in h_power:
                try: s.state = float(s.state) * self.power_scale_factor
                except: pass
        b_power = data_helpers.bin_data(h_power, bin_period, start, rounded_now)

        h_temp = self.ha.get_history(self.level_entity_id, start_time=start, end_time=rounded_now)
        b_temp = data_helpers.bin_data(h_temp, bin_period, start, rounded_now)

        if not b_power or not b_temp or len(b_power) < 2 or len(b_power) != len(b_temp):
            return None

        cap_kwh = (self.volume_l * 4.186 * (self.temp_max - self.temp_min)) / 3600.0
        dt_hr = bin_period / 60.0
        history_by_tod = defaultdict(list)
        
        for i in range(1, len(b_temp)):
            p_heat = b_power[i].avg_state or 0.0
            t1, t2 = b_temp[i-1].avg_state, b_temp[i].avg_state
            
            if t1 is not None and t2 is not None:
                e1 = max(0.0, (t1 - self.temp_min) / (self.temp_max - self.temp_min)) * cap_kwh
                e2 = max(0.0, (t2 - self.temp_min) / (self.temp_max - self.temp_min)) * cap_kwh
                p_draw = p_heat - (e2 - e1) / dt_hr
                history_by_tod[b_temp[i].time.time()].append(max(0.0, p_draw))

        if not history_by_tod: return None
        self.avg_draw_day = {tod: sum(vals)/len(vals) for tod, vals in history_by_tod.items()}
        self.last_draw_data_retrival_timestamp = now_ts
        return self.avg_draw_day

    def forecast_draw_power(self, time_index) -> np.ndarray:
        avg_draw = self.get_draw_avg()
        if not avg_draw: return np.full(len(time_index), 0.1)
        global_avg = sum(avg_draw.values()) / len(avg_draw)
        return np.array([avg_draw.get(t.time(), global_avg) for t in time_index])

    def get_results(self, dt):
        p_hw = self.p_hw.value
        if p_hw is None: return {}
        p_res = [round(float(x), 2) for x in p_hw.tolist()]
        

        soc_pct = [round((x / self.capacity_kwh) * 100, 2) if self.capacity_kwh > 0 else 0 for x in self.hw_energy.value.tolist()]
        return {
            "hw_power": p_res,
            "hw_soc_percent": soc_pct,
            "power": p_res
        }

    @classmethod
    def from_dict(cls, item: dict[str, Any]) -> "HWLoad | None":
        if not item:
            return None

        return cls(
            name=str(item.get("name", "Unknown")),
            load_type=str(item.get("load_type", "hot_water")),
            reward_cents_per_kwh=float(item.get("reward_cents_per_kwh", 0.0) or 0.0),
            debias_load=bool(item.get("debias_load", False)),
            volume_l=float(item.get("volume_l", 0.0) or 0.0),
            temp_min=float(item.get("temp_min", 0.0) or 0.0),
            temp_max=float(item.get("temp_max", 0.0) or 0.0),
            power_entity_id=str(item.get("power_entity_id", "")),
            max_charge_power_entity_id=str(item.get("max_charge_power_entity_id", "")),
            plugged_in_entity_id=str(item.get("plugged_in_entity_id", "")),
            level_entity_id=str(item.get("level_entity_id", "")),
            hw_power_unit_scale=str(item.get("hw_power_unit_scale", "kW"))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "load_type": self.load_type,
            "reward_cents_per_kwh": self.reward_cents_per_kwh,
            "debias_load": self.debias_load,
            "volume_l": self.volume_l,
            "temp_min": self.temp_min,
            "temp_max": self.temp_max,
            "power_entity_id": self.power_entity_id,
            "max_charge_power_entity_id": self.max_charge_power_entity_id,
            "plugged_in_entity_id": self.plugged_in_entity_id,
            "level_entity_id": self.level_entity_id,
            "hw_power_unit_scale": self.hw_power_unit_scale
        }