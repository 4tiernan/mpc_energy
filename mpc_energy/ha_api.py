import requests
from typing import Any, Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import logging

logger = logging.getLogger(__name__)

@dataclass
class History:
    state: float
    time: datetime

HA_TZ = ZoneInfo("Australia/Brisbane") 

class HomeAssistantAPI:
    def __init__(self, base_url, token, errors):
        self.base_url = base_url.rstrip('/')
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        self.errors = errors

    def check_api_running(self): #Checks to see if we can connect to the ha api
        url = f"{self.base_url}/api/"
        response = self.ha_request(url, "get")
        return response.get("message") == "API running."

    def ha_request(self, url, method, data=None, params = None, headers = None):
        if(headers == None):
            headers = self.headers
        try:
            if(method =='get'):
                r = requests.get(url, headers=headers, params=params)
                r.raise_for_status()
                return r.json()
            elif(method == 'post'):
                r = requests.post(url, json=data, headers=headers)
                r.raise_for_status()
                return r.json()
            else: 
                raise Exception(f"Method not get or post: {method}")
        except Exception as e:
            if(self.check_api_running()):
                entity_id = url.split("/api/states/")[-1]
                logger.error(f"Able to connect to HA API but the entity {entity_id} was not found. Is it disabled?")
            else:
                raise Exception(f"Unable to connect to HA, exception: {e}")
    
    def get_state(self, entity_id):
        url = f"{self.base_url}/api/states/{entity_id}"
        return self.ha_request(url=url, method='get')
    
    def get_numeric_state(self, entity_id):
        json_resp = self.get_state(entity_id)
        return float(json_resp["state"])

    def call_service(self, domain, service, data):
        url = f"{self.base_url}/api/services/{domain}/{service}"
        return self.ha_request(url=url, data=data, method='post')

    def send_notification(self, title, msg, target):
        self.call_service(
            "notify",
            target,
            {
                "title": title,
                "message": msg
            }
        )
    
    def get_history(self, entity_id, start_time=None, end_time=None, type=float):
        """Fetch history for a specific entity.
        Home Assistant requires:
        /api/history/period/<start>?end_time=...&filter_entity_id=...
        """
        if not start_time:
            raise ValueError("start_time is required for history endpoint")

        url = self.base_url+f"/api/history/period/{start_time}"
        params = {"filter_entity_id": entity_id}
        if end_time:
            params["end_time"] = end_time

        response = self.ha_request(url=url, method='get', params=params)
        history = []
        date_format = "%Y-%m-%dT%H:%M:%S"
        for i in response[0]:
            state_time = datetime.fromisoformat(i["last_updated"])
            state_time = state_time.astimezone(HA_TZ)
            if(type == float):
                try:
                    state_value = float(i["state"])
                except:
                    state_value = None
            elif(type == str):
                try:
                    state_value = str(i["state"])
                except:
                    state_value = None
                
            history.append(History(state=state_value, time=state_time))
        return history
    
    def set_switch_state(self, entity_id: str, state: bool):
        if(state == True):
            self.call_service("switch", "turn_on", {"entity_id": entity_id})
        elif(state == False):
            self.call_service("switch", "turn_off", {"entity_id": entity_id})
        else:
            if(self.errors):
                raise("Switch state must be True or False not: "+str(state))

    def set_number(self, entity_id, value):
        return self.call_service("number", "set_value", {
            "entity_id": entity_id,
            "value": value
        })

    def set_input_number(self, entity_id, value):
        return self.call_service("input_number", "set_value", {
            "entity_id": entity_id,
            "value": value
        })
    
    def set_select(self, entity_id, option):
        if entity_id.startswith("input_select."):
            domain = "input_select"
        else:
            domain = "select"

        service = "select_option"
        data = {
            "entity_id": entity_id,
            "option": option,
        }
        return self.call_service(domain, service, data)

    def fire_event(self, event_type, data=None):
        data = data or {}
        url = f"{self.base_url}/api/events/{event_type}"
        return self.ha_request(url=url, method='post', data=data)
