from typing import Any, List, Dict
from loads.optional_loads import OptionalLoad
import cvxpy as cp
import numpy as np
from mpc_logger import logger
import datetime
import data_helpers

class TimedLoad(OptionalLoad):
    """
    Load that must run for a specific duration within a specific cycle.
    Example: 2 hours every 96 hours.
    """
    def __init__(
        self,
        name: str,
        load_type: str,
        reward_cents_per_kwh: float,
        debias_load: bool,
        power_kw: float,
        run_duration_hours: float,
        cycle_hours: float,
        switch_entity_id: str,
        power_entity_id: str = "",
    ):
        super().__init__(name, load_type, reward_cents_per_kwh, debias_load)
        self.power_kw = float(power_kw)
        self.run_duration_hours = float(run_duration_hours)
        self.cycle_hours = float(cycle_hours)
        self.switch_entity_id = switch_entity_id
        self.power_entity_id = power_entity_id
        
        self.current_power_kw = 0.0
        self.remaining_runtime_needed = 0.0
        self.target_state = False

    def update_data(self) -> None:
        """Calculate remaining runtime needed in the sliding window using HA history."""
        # Fetch history for the specified cycle window
        hist_power = self.get_historical_power(hours=self.cycle_hours)
        
        if hist_power:
            # Count bins where power was active (> 40% of rated power)
            threshold = self.power_kw * 0.4
            active_bins = sum(1 for b in hist_power if b.avg_state is not None and b.avg_state > threshold)
            # Each bin in the historical power request is 5 minutes
            run_time_hours = active_bins * (5 / 60.0)
        else:
            run_time_hours = 0.0
            
        self.remaining_runtime_needed = max(0.0, self.run_duration_hours - run_time_hours)
        
        if self.power_entity_id:
            try:
                self.current_power_kw = self.ha.get_numeric_state(self.power_entity_id)
            except:
                self.current_power_kw = 0.0
        
        logger.debug(f"TimedLoad '{self.name}': Run last {self.cycle_hours}h: {run_time_hours:.2f}h. Remaining needed: {self.remaining_runtime_needed:.2f}h")

    def build_cvxpy(self, mpc):
        n = int(mpc.N_5min)
        dt = mpc.dt_5min
        
        self.p_timed = cp.Variable(n, nonneg=True, name=f"{self.name}_p")
        self.debt_unmet = cp.Variable(nonneg=True, name=f"{self.name}_unmet")
        
        # Parameters
        self.p_max_param = cp.Parameter(nonneg=True, name=f"{self.name}_p_max")
        self.needed_param = cp.Parameter(nonneg=True, name=f"{self.name}_needed")
        
        # Constraints: 0 <= p <= power_kw, and sum(p*dt) >= remaining_needed
        constraints = [
            self.p_timed <= self.p_max_param,
            cp.sum(self.p_timed) * dt >= self.needed_param - self.debt_unmet
        ]
        
        reward_dollars = self.reward_cents_per_kwh / 100.0
        objective_term = (
            self.debt_unmet * 1000.0  # High penalty for failure to meet runtime requirement
            - cp.sum(self.p_timed) * dt * reward_dollars # Incentive to run at optimal times
        )
        
        return constraints, objective_term, self.p_timed

    def disable_load(self, mpc):
        self.p_max_param.value = 0.0
        self.needed_param.value = 0.0

    def update_mpc_values(self, mpc, time_index):
        self.update_data()
        self.p_max_param.value = self.power_kw
        # We can't require more runtime in this horizon than the horizon's total duration
        max_possible_in_horizon = int(mpc.N_5min) * mpc.dt_5min
        self.needed_param.value = min(self.remaining_runtime_needed, max_possible_in_horizon)

    def get_results(self, dt):
        p_vals = self.p_timed.value
        if p_vals is None: return {}
        
        p_res = [round(float(x), 2) for x in p_vals.tolist()]
        self.target_state = p_res[0] > (self.power_kw * 0.4)
        
        if self.switch_entity_id:
            try:
                self.ha.set_switch_state(self.switch_entity_id, self.target_state)
            except Exception as e:
                logger.error(f"TimedLoad '{self.name}': Failed to set switch '{self.switch_entity_id}': {e}")

        return {
            "power": p_res,
            "raw_power": p_res,
            "soc_percent": [100.0 if x > (self.power_kw * 0.4) else 0.0 for x in p_res]
        }

    @classmethod
    def from_dict(cls, item: dict[str, Any]) -> "TimedLoad | None":
        if not item: return None
        return cls(
            name=str(item.get("name", "Unknown")),
            load_type=str(item.get("load_type", "timed")),
            reward_cents_per_kwh=float(item.get("reward_cents_per_kwh", 0.0) or 0.0),
            debias_load=bool(item.get("debias_load", False)),
            power_kw=float(item.get("power_kw", 0.0) or 0.0),
            run_duration_hours=float(item.get("run_duration_hours", 0.0) or 0.0),
            cycle_hours=float(item.get("cycle_hours", 0.0) or 0.0),
            switch_entity_id=str(item.get("switch_entity_id", "")),
            power_entity_id=str(item.get("power_entity_id", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "load_type": self.load_type,
            "reward_cents_per_kwh": self.reward_cents_per_kwh,
            "debias_load": self.debias_load,
            "power_kw": self.power_kw,
            "run_duration_hours": self.run_duration_hours,
            "cycle_hours": self.cycle_hours,
            "switch_entity_id": self.switch_entity_id,
            "power_entity_id": self.power_entity_id,
        }