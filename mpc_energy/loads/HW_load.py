from typing import Any, List, Tuple
from optional_loads import OptionalLoad
import cvxpy as cp
import numpy as np
from mpc_logger import logger

class HWLoad(OptionalLoad):
    """
    Specialized load for Hot Water systems.
    Converts temperature and volume into energy (kWh) and percentage level.
    """
    def __init__(self, *args, **kwargs):
        self.volume_l = float(kwargs.pop("volume_l", 0.0))
        self.temp_min = float(kwargs.pop("temp_min", 0.0))
        self.temp_max = float(kwargs.pop("temp_max", 0.0))
        super().__init__(*args, **kwargs)

    def update_data(self, ha) -> None:
        # Update basic power and plugged-in status
        self.current_power_kw = self._get_numeric(ha, self.power_entity_id)
        self.max_charge_power_limit = self._get_numeric(ha, self.max_charge_power_entity_id)
        self.is_plugged_in = self._get_bool(ha, self.plugged_in_entity_id) if self.plugged_in_entity_id else True

        # Thermal to Energy Conversion
        raw_temp = self._get_numeric(ha, self.level_entity_id) if self.level_entity_id else 0.0
        
        if self.volume_l > 0 and self.temp_max > self.temp_min:
            # Energy Capacity (kWh) = (Volume * 4.186 * deltaT) / 3600
            self.capacity_kwh = (self.volume_l * 4.186 * (self.temp_max - self.temp_min)) / 3600.0
            # Calculate level based on current temperature: % = (current_T - T_min) / (T_max - T_min)
            self.current_level_percent = min(max((raw_temp - self.temp_min) / (self.temp_max - self.temp_min) * 100.0, 0.0), 100.0)
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

    def update_values(self, n, dt, time_index, load_5min):
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
        base = super().from_dict(item)
        if not base: return None
        base.volume_l = float(item.get("volume_l", 0.0))
        base.temp_min = float(item.get("temp_min", 0.0))
        base.temp_max = float(item.get("temp_max", 0.0))
        return base

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update({
            "volume_l": self.volume_l,
            "temp_min": self.temp_min,
            "temp_max": self.temp_max
        })
        return data