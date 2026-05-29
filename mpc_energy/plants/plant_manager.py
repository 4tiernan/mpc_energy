import os
import json
from plants.sigenergy_plant import SigEnergyPlant
from plants.goodwe_plant import GoodWePlant
from plants.base_plant import BasePlant
from exceptions import MPCEnergyError
from mpc_logger import logger

CONFIG_PATH = "/data/plant_config.json"

def load_plant_config():
    """
    Loads the plant configuration from the JSON file.
    Returns an empty dictionary if the file does not exist or is malformed.
    """
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.error(f"Error decoding plant config from {CONFIG_PATH}. Returning empty config.")
            return {}
        except Exception as e:
            logger.error(f"Error reading plant config from {CONFIG_PATH}: {e}. Returning empty config.")
            return {}
    return {}

def GetPlant(ha, opt_loads) -> BasePlant:
    plant_config = load_plant_config()
    brand = plant_config.get("plant_brand", "Sigenergy")
    
    if brand == "Sigenergy" or brand == "SigEnergy":
        plant = SigEnergyPlant(ha, opt_loads, plant_config)
    elif brand == "Goodwe" or brand == "GoodWe":
        plant = GoodWePlant(ha, opt_loads, plant_config)
    else:
        logger.warning(f"Unknown plant brand '{brand}' selected in configuration. Defaulting to SigenergyPlant.")
        plant = SigEnergyPlant(ha, opt_loads, plant_config)
    return plant