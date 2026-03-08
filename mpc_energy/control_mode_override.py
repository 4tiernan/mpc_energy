import time
from mpc_logger import logger


class ControlModeOverrideManager:
    def __init__(self, ha_mqtt, energy_controller, plant):
        self.ha_mqtt = ha_mqtt
        self.energy_controller = energy_controller
        self.plant = plant
        self.state = {"active": False, "mode": None, "expiry_timestamp": 0, "start_price": None}

    def parse_override_duration_minutes(self):
        selected_duration = self.ha_mqtt.control_mode_override_duration_selector.state
        if(selected_duration is None):
            return 15

        if(selected_duration == "Till Price Change"):
            return None

        try:
            duration_minutes = int(selected_duration)
        except ValueError:
            logger.warning(f"Invalid override duration '{selected_duration}'. Falling back to 15 minutes.")
            return 15

        if(duration_minutes not in [5, 15, 30, 60]):
            logger.warning(f"Unsupported override duration '{duration_minutes}'. Falling back to 15 minutes.")
            return 15

        return duration_minutes

    def apply_override_mode(self, mode):
        if(mode == "Dispatching"):
            self.energy_controller.dispatch()
        elif(mode == "Exporting All Solar"):
            self.energy_controller.export_all_solar()
        elif(mode == "Exporting Excess Solar"):
            self.energy_controller.export_excess_solar()
        elif(mode == "Self Consumption"):
            self.energy_controller.self_consumption()
        elif(mode == "Grid Import"):
            self.energy_controller.import_power()
        elif(mode == "Solar To Load"):
            self.energy_controller.solar_to_load()
        else:
            raise Exception(f"Unsupported control mode override '{mode}'")

    def reset(self):
        self.state = {"active": False, "mode": None, "expiry_timestamp": 0, "start_price": None}

    def get_price_for_mode(self, mode, amber_data):
        ''' Selects the import or export price based on whether the selected mode will import or export power. '''
        import_price_modes = ["Grid Import"]

        if(mode in import_price_modes):
            return amber_data.general_price

        return amber_data.feedIn_price

    def run(self, amber_data):
        requested_mode = self.ha_mqtt.control_mode_override_selector.state

        if(requested_mode is None or requested_mode == "Disabled"):
            if(self.state["active"]):
                logger.warning("Control mode override disabled by user.")
                self.reset()
            return False

        price_mode = self.state["mode"] if self.state["active"] else requested_mode
        current_price = self.get_price_for_mode(price_mode, amber_data)

        if(not self.state["active"] or self.state["mode"] != requested_mode):
            duration_minutes = self.parse_override_duration_minutes()
            expiry_timestamp = 0 if duration_minutes is None else time.time() + duration_minutes * 60

            self.state = {
                "active": True,
                "mode": requested_mode,
                "expiry_timestamp": expiry_timestamp,
                "start_price": current_price
            }

            if(duration_minutes is None):
                logger.warning(f"Control mode override started: {requested_mode} until price changes.")
            else:
                logger.warning(f"Control mode override started: {requested_mode} for {duration_minutes} minutes (until price changes).")

        if(current_price != self.state["start_price"]):
            logger.warning(f"Control mode override ended due to price change from {self.state['start_price']} to {current_price} c/kWh.")
            self.reset()
            self.ha_mqtt.control_mode_override_selector.set_state("Disabled")
            return False

        if(self.state["expiry_timestamp"] > 0 and time.time() >= self.state["expiry_timestamp"]):
            logger.warning(f"Control mode override ended after requested duration in mode {self.state['mode']}.")
            self.reset()
            self.ha_mqtt.control_mode_override_selector.set_state("Disabled")
            return False

        self.apply_override_mode(self.state["mode"])
        return True
