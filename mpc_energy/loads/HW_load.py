from typing import Any
from ..optional_loads import OptionalLoad

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