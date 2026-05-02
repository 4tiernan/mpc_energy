from typing import Any
from optional_loads import OptionalLoad

class EVLoad(OptionalLoad):
    """
    Specialized load for Electric Vehicles. 
    Uses standard percentage logic for SOC.
    """
    def update_data(self, ha) -> None:
        # EV logic is currently identical to the generic OptionalLoad update_data
        # but separated here for future specialized charging logic.
        super().update_data(ha)

    @classmethod
    def from_dict(cls, item: dict[str, Any]) -> "EVLoad | None":
        return super().from_dict(item)