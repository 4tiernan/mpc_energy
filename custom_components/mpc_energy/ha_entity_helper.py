from homeassistant.components.recorder.history import state_changes_during_period
from homeassistant.util.dt import as_utc

from dataclasses import dataclass
import datetime
from zoneinfo import ZoneInfo


@dataclass
class History:
    state: float
    time: datetime

HA_TZ = ZoneInfo("Australia/Brisbane") 

class HAEntityHelper:
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
    
    def get_state(self, entity_id, as_type=float):
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        elif as_type == float:
            try: 
                return float(state.state)
            except:
                return None
        elif as_type == str:
            try:
                return str(state.state)
            except:
                return None
    
    def get_numeric_state(self, entity_id):
        return self.get_state(entity_id, type=float)
    
    def get_entity_id(self, entity_reference):
        return self.entry.data[entity_reference] # Convert from a entry reference to a ha entity id

    async def get_history(self, entity_reference, start_time, end_time, as_type=float):
        """Fetch history for a specific entity.
            Returns:
            List of History objs from oldest to newest (-1 index will be the most recent data):
            [
                history.time": state datetime,
                history.state": state value
                ...
            ]
        """
        entity_id = self.get_entity_id(entity_reference) # Convert from a entry reference to a ha entity id

        if not start_time:
            raise ValueError("start_time is required for history endpoint")
        if not end_time:
            raise ValueError("end_time is required for history endpoint")
        

        start_utc = as_utc(start_time)
        end_utc = as_utc(end_time)
        history = []


        async for item in state_changes_during_period(
            self.hass,
            start_utc,
            end_utc,
            entity_ids=[entity_id]
        ):
            for state in item:
                state_value = None
                if as_type == float:
                    try:
                        state_value = float(state.state)
                    except (ValueError, TypeError):
                        state_value = None
                elif as_type == str:
                    state_value = str(state.state)

                history.append({
                    "state": state_value,
                    "time": state.last_updated
                })

        return history
    
    def call_service(self, domain: str, service: str, data: dict):
        """Wrapper around hass.services.call"""
        return self.hass.services.call(domain, service, data)
    
    def set_entity_state(self, entity_reference, value):
        """
        Generic setter for switches, numbers, input_numbers, and selects.
        Determines domain and service automatically.
        """
        entity_id = self.get_entity_id(entity_reference) # Convert from a entry reference to a ha entity id

        domain = entity_id.split(".")[0]  # switch, number, input_number, input_select, select, etc.

        if domain == "switch":
            service = "turn_on" if value else "turn_off"
            data = {"entity_id": entity_id}

        elif domain in ["number", "input_number"]:
            service = "set_value"
            data = {"entity_id": entity_id, "value": value}

        elif domain in ["select", "input_select"]:
            service = "select_option"
            data = {"entity_id": entity_id, "option": value}

        else:
            if self.errors:
                raise ValueError(f"Unsupported entity domain '{domain}' for set_entity_state")
            return None

        return self.call_service(domain, service, data)