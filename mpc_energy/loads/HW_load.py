from typing import Any, List, Tuple
from loads.optional_loads import OptionalLoad
import cvxpy as cp
import numpy as np
from mpc_logger import logger

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
        level_entity_id: str = ""
    ):
        super().__init__(name, load_type, reward_cents_per_kwh, debias_load)
        self.volume_l = float(volume_l)
        self.temp_min = float(temp_min)
        self.temp_max = float(temp_max)
        self.power_entity_id = power_entity_id
        self.max_charge_power_entity_id = max_charge_power_entity_id
        self.plugged_in_entity_id = plugged_in_entity_id
        self.level_entity_id = level_entity_id

        # Internal state
        self.current_power_kw = 0.0
        self.max_charge_power_limit = 0.0
        self.is_plugged_in = False
        self.capacity_kwh = 0.0
        self.current_level_percent = 0.0
        self.current_charge_kwh = 0.0

    def update_data(self, ha) -> None:
        # Update basic power and plugged-in status
        self.current_power_kw = ha.get_numeric_state(self.power_entity_id) if self.power_entity_id else 0.0
        self.max_charge_power_limit = ha.get_numeric_state(self.max_charge_power_entity_id) if self.max_charge_power_entity_id else 3.6
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

    def build_cvxpy(self, n, dt, mpc_soc, mpc_soc_min_param):
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
        
        # Maintenance reward
        objective_term = - cp.sum(self.hw_energy) * 0.001
        
        return constraints, objective_term, self.p_hw

    def update_mpc_values(self, n, dt, time_index, load_5min):
        self.soc_init_param.value = float(self.current_charge_kwh)
        self.p_max_limit_param.value = float(self.max_charge_power_limit or 3.6)
        
        # Simple draw heuristic (morning/evening peaks)
        draw = np.zeros(n)
        for i, t in enumerate(time_index):
            if 6 <= t.hour <= 8 or 18 <= t.hour <= 21:
                draw[i] = 1.0 # 1kW thermal equivalent draw
        self.draw_forecast_param.value = draw

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
            level_entity_id=str(item.get("level_entity_id", ""))
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
        }