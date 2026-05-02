from typing import Any, Tuple, List
from optional_loads import OptionalLoad
import cvxpy as cp
import numpy as np
from datetime import datetime, timedelta
from mpc_logger import logger

class EVLoad(OptionalLoad):
    def update_data(self, ha) -> None:
        super().update_data(ha)
        self.target_charge_rate = 0.0

    def debias_load(self, current_load, historical_data):
        if "ev_power" in historical_data and len(historical_data["ev_power"]) > 0:
            current_ev_kw = max(historical_data["ev_power"][-1], 0.0)
            return max(current_load - current_ev_kw, 0.0)
        return current_load
        
    def get_historical_power(self, start, end, bin_period):
        if not self.power_entity_id: return None
        
        history = self.ha.get_history(self.power_entity_id, start_time=start, end_time=end)
        if not history: return None
        
        requested_seconds = max((end - start).total_seconds(), 1.0)
        ev_span_seconds = max((history[-1].time - history[0].time).total_seconds(), 0.0)
        coverage = ev_span_seconds / requested_seconds
        
        if coverage < 0.5:
            logger.warning(f"Insufficient history coverage ({round(coverage*100)}%) for EV load {self.name}. Skipping debias.")
            return None
            
        binned = self.plant.bin_data(history, bin_period, start, end, interpolation_method="step")
        return binned

    def build_cvxpy(self, n, dt, mpc_soc, mpc_soc_min_param):
        self.p_ev = cp.Variable(n, nonneg=True)
        self.ev_soc = cp.Variable(n + 1)
        
        self.p_max_param = cp.Parameter(n, nonneg=True)
        self.soc_init_param = cp.Parameter(nonneg=True)
        self.soc_upper_limit_param = cp.Parameter(nonneg=True)
        self.soc_min_required_param = cp.Parameter(n, nonneg=True)
        self.charge_reward_mask_param = cp.Parameter(n, nonneg=True)
        self.maintain_reward_param = cp.Parameter(nonneg=True)

        constraints = [
            self.ev_soc[0] == self.soc_init_param,
            self.ev_soc[1:] == self.ev_soc[:-1] + (dt * self.p_ev),
            self.ev_soc[1:] >= 0,
            self.ev_soc[1:] <= self.soc_upper_limit_param,
            self.ev_soc[1:] >= self.soc_min_required_param,
            self.p_ev >= 0,
            self.p_ev <= self.p_max_param,
            mpc_soc[1:] >= self.p_ev * dt + mpc_soc_min_param
        ]

        objective_term = (
            - cp.sum(cp.multiply(self.charge_reward_mask_param, self.p_ev)) * dt
            - cp.sum(cp.multiply(self.maintain_reward_param, self.ev_soc[0:-1])) * dt
        )

        return constraints, objective_term, self.p_ev

    def update_values(self, n, dt, time_index, load_5min):
        self.soc_init_param.value = float(self.current_charge_kwh)
        self.soc_upper_limit_param.value = (self.max_limit / 100.0) * self.capacity_kwh

        # Mode detection via HA MQTT
        mode = "Solar Smart"
        if self.ha_mqtt and hasattr(self.ha_mqtt, "ev_charging_mode_selector"):
            mode = self.ha_mqtt.ev_charging_mode_selector.state or "Solar Smart"

        # Build power limits
        p_max_arr = np.zeros(n, dtype=float)
        grid_import_limit = self.plant.max_import_power
        ev_max_limit = self.max_charge_power_limit or 7.0 # Fallback if sensor missing
        
        for i, load in enumerate(load_5min):
            max_avail = grid_import_limit - load
            p_max_arr[i] = max(0.0, min(ev_max_limit, max_avail))
        self.p_max_param.value = p_max_arr

        # Reward
        divisor = max(n * dt * (self.capacity_kwh - self.current_charge_kwh), 1.0)
        self.maintain_reward_param.value = 0.20 / divisor

        # SOC constraints
        soc_min_req = np.zeros(n, dtype=float)
        min_target_kwh = (self.min_limit / 100.0) * self.capacity_kwh
        max_target_kwh = (self.max_limit / 100.0) * self.capacity_kwh

        if self.current_charge_kwh < min_target_kwh:
            for i in range(n):
                soc_min_req[i] = min(self.current_charge_kwh + i * p_max_arr[i] * 0.95 * dt, min_target_kwh)
        else:
            if mode == "Ready by Time":
                soc_min_req = self._build_ready_by_mask(n, dt, time_index, max_target_kwh)
            elif mode == "Force On":
                for i in range(n):
                    soc_min_req[i] = min(self.current_charge_kwh + i * p_max_arr[i] * 0.95 * dt, max_target_kwh)
            elif mode == "Charging Disabled":
                self.p_max_param.value = np.zeros(n, dtype=float)

        self.soc_min_required_param.value = soc_min_req
        
        # Reward Mask (48h)
        mask = np.zeros(n, dtype=float)
        charge_reward = (self.charge_reward_cents_per_kwh / 100.0) + 0.03
        steps_48h = int(48 / dt)
        mask[:min(n, steps_48h)] = charge_reward
        self.charge_reward_mask_param.value = mask

    def _build_ready_by_mask(self, n, dt, time_index, target_kwh):
        ready_time_str = "07:00"
        if self.ha_mqtt and hasattr(self.ha_mqtt, "ready_by_time_selector"):
            ready_time_str = self.ha_mqtt.ready_by_time_selector.state or "07:00"
            
        required_mask = np.zeros(n, dtype=float)
        try:
            hour, minute = [int(v) for v in ready_time_str.split(":")]
            target = datetime.now(self.local_tz).replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target < time_index[0]: target += timedelta(days=1)
            
            hold_end = target + timedelta(hours=1)
            for idx, step_time in enumerate(time_index):
                if target <= step_time <= hold_end:
                    required_mask[idx] = target_kwh
        except:
            pass
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

    @classmethod
    def from_dict(cls, item: dict[str, Any]) -> "EVLoad | None":
        return super().from_dict(item)