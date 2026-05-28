from typing import Any, List, Tuple, Dict
from loads.optional_loads import OptionalLoad
import cvxpy as cp
import numpy as np
from mpc_logger import logger
import datetime
import time
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
        level_entity_id: str = "",
        hw_power_unit_scale: str = "kW",
    ):
        super().__init__(name, load_type, reward_cents_per_kwh, debias_load)
        self.reward_dollars_per_kwh = self.reward_cents_per_kwh / 100.0
        self.volume_l = float(volume_l)
        self.temp_min = float(temp_min)
        self.temp_max = float(temp_max)
        self.power_entity_id = power_entity_id
        self.max_charge_power_entity_id = max_charge_power_entity_id
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

        logger.debug(f"Initialized HWLoad '{self.name}' with scale={self.hw_power_unit_scale}, volume={self.volume_l}L, temp_min={self.temp_min}°C, temp_max={self.temp_max}°C, power_entity_id='{self.power_entity_id}', max_charge_power_entity_id='{self.max_charge_power_entity_id}', level_entity_id='{self.level_entity_id}'")

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

        logger.debug(f"Updated HWLoad '{self.name}' data: current_power_kw={self.current_power_kw:.2f}kW, max_charge_power_limit={self.max_charge_power_limit:.2f}kW, is_plugged_in={self.is_plugged_in}, raw_temp={raw_temp:.2f}°C, capacity_kwh={self.capacity_kwh:.2f}kWh, current_level_percent={self.current_level_percent:.2f}%, current_charge_kwh={self.current_charge_kwh:.2f}kWh")

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
        # shortfall represents thermal usage that couldn't be met (i.e. water is cold).
        # it prevents infeasibility when predicted usage spikes exceed heater capacity.
        self.shortfall = cp.Variable(n, nonneg=True)
        
        self.soc_init_param = cp.Parameter(nonneg=True)
        self.capacity_param = cp.Parameter(nonneg=True)
        self.draw_forecast_param = cp.Parameter(n) # Allow negative values for solar gains
        self.p_max_limit_param = cp.Parameter(nonneg=True)
        
        constraints = [
            self.hw_energy[0] == self.soc_init_param,
            self.hw_energy[1:] == self.hw_energy[:-1] + (self.p_hw * dt) - ((self.draw_forecast_param - self.shortfall) * dt),
            self.hw_energy >= -0.001, # Small epsilon to prevent precision-based infeasibility
            self.hw_energy <= self.capacity_param + 0.001,
            self.p_hw <= self.p_max_limit_param,
            # Allow shortfall to only cover positive draws (usage). Gains (solar) can't have shortfall.
            self.shortfall <= cp.maximum(0, self.draw_forecast_param)
        ]
        
        # Maintenance reward: Tiny incentive to keep the tank full
        # User reward: Incentivize heating when prices are low or solar is excess
        # Shortfall penalty: High cost ensures shortfall is only used to prevent infeasibility.
        objective_term = -cp.multiply(self.reward_dollars_per_kwh, self.p_hw) * dt \
                        +cp.multiply(self.shortfall, 10.0)*dt # High Penalty for shortfall

        return constraints, objective_term, self.p_hw

    def update_mpc_values(self, mpc, time_index):
        self.update_data()
        n = mpc.N_5min
        
        self.soc_init_param.value = float(self.current_charge_kwh)
        self.capacity_param.value = float(self.capacity_kwh)
        self.p_max_limit_param.value = float(self.max_charge_power_limit or 3.6)
        
        # Model thermal draw (usage + losses) based on historical temperature deltas
        hot_water_delta_forecast = self.forecast_temp_delta(time_index)

        # Convert temperature delta (°C per 5-min bin) to Power (kW)
        # Power (kW) = (delta_T * Volume * 4.186) / (3600 seconds * (5/60) hours)
        # P = (delta_T * Volume * 4.186) / 300
        # Sign is flipped because hot_water_delta_forecast is + for heating, but draw_forecast is + for cooling.
        draw_forecast = -hot_water_delta_forecast * (self.volume_l * 4.186) / 300.0
        
        self.draw_forecast_param.value = draw_forecast

        # Debug logging to console
        logger.debug(f"HWLoad '{self.name}' draw forecast: min={np.min(draw_forecast):.2f}kW, max={np.max(draw_forecast):.2f}kW, avg={np.mean(draw_forecast):.2f}kW")

    def get_temp_delta_avg(self, days_ago=None, hours_update_interval=24):
        """Calculate the average temperature delta (cooling rate) profile for a day."""
        if days_ago is None:
            days_ago = self.load_avg_days

        now_ts = time.time()
        if (self.avg_delta_day is not None and 
            now_ts - self.last_delta_data_retrival_timestamp < hours_update_interval * 3600):
            return self.avg_delta_day

        bin_period = 5
        now = datetime.datetime.now(self.local_tz)
        rounded_now = data_helpers.round_minutes(now, bin_period)
        start = rounded_now - datetime.timedelta(days=days_ago)

        if not self.level_entity_id:
            logger.warning(f"No Tank Temperature Entity ID configured for HWLoad '{self.name}'. Cannot calculate historical deltas.")
            return None

        h_temp = self.ha.get_history(self.level_entity_id, start_time=start, end_time=rounded_now)
        b_temp = data_helpers.bin_data(h_temp, bin_period, start, rounded_now)

        if not b_temp or len(b_temp) < 2:
            return None

        history_by_tod = defaultdict(list)
        
        for i in range(1, len(b_temp)):
            t1, t2 = b_temp[i-1].avg_state, b_temp[i].avg_state
            
            if t1 is not None and t2 is not None:
                # Delta: + when increasing, - when decreasing
                delta = t2 - t1
                history_by_tod[b_temp[i].time.time()].append(delta)
                

        if not history_by_tod: return None

        # Calculate raw averages per time-of-day
        raw_avg_dict = {tod: sum(vals)/len(vals) for tod, vals in history_by_tod.items()}
        
        # 30-min Moving Average Smoothing (cyclic over 24h)
        # Create a full 288-bin day (5-min bins)
        all_tods = [(datetime.datetime.min + datetime.timedelta(minutes=i*5)).time() for i in range(288)]
        deltas = np.array([raw_avg_dict.get(t, np.nan) for t in all_tods])
        
        # Cyclic interpolation of missing data points
        if np.isnan(deltas).any():
            if np.isnan(deltas).all():
                deltas = np.zeros(288)
            else:
                valid_idx = np.where(~np.isnan(deltas))[0]
                deltas = np.interp(np.arange(288), valid_idx, deltas[valid_idx], period=288)

        # Apply 30 min (6 bins) cyclic moving average
        window = 6
        kernel = np.ones(window) / window
        smoothed = np.convolve(np.tile(deltas, 3), kernel, mode='same')[288:576]

        self.avg_delta_day = {all_tods[i]: smoothed[i] for i in range(288)}
        self.last_delta_data_retrival_timestamp = now_ts
        return self.avg_delta_day

    def forecast_temp_delta(self, time_index) -> np.ndarray:
        avg_delta = self.get_temp_delta_avg()
        if not avg_delta:
            logger.warning(f"No historical temperature delta data available for HWLoad '{self.name}'. Using default small negative delta.")
            return np.full(len(time_index), -0.01) # Default tiny loss (negative delta)
        global_avg = sum(avg_delta.values()) / len(avg_delta)
        return np.array([avg_delta.get(t.time(), global_avg) for t in time_index])

    def get_results(self, dt):
        p_hw = self.p_hw.value
        if p_hw is None or self.hw_energy.value is None: return {}
        p_res = [round(float(x), 2) for x in p_hw.tolist()]
        
        hw_energy_val = self.hw_energy.value
        soc_pct = [round((x / self.capacity_kwh) * 100, 2) if self.capacity_kwh > 0 else 0 for x in hw_energy_val.tolist()]
        
        # Calculate temperature: T = T_min + (E/Cap) * (T_max - T_min)
        delta_t = self.temp_max - self.temp_min
        temp_c = [round(self.temp_min + (x / self.capacity_kwh) * delta_t, 1) if self.capacity_kwh > 0 else self.temp_min for x in hw_energy_val.tolist()]

        return {
            "raw_power": p_res,
            "power": p_res,
            "soc_percent": soc_pct,
            "temp_c": temp_c
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
            "level_entity_id": self.level_entity_id,
            "hw_power_unit_scale": self.hw_power_unit_scale
        }