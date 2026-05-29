import logging
import colorlog

import json

with open("/data/options.json") as f:
    options = json.load(f)

def get_entity_id(key, default=None):
    value = options.get(key, default)
    if((value == None or value == "") and default == None):
        raise Exception(f"Missing required configuration: {key}. \n Please ensure this value has been set in the app configuration page and restart the app.") from None
    return value


configured_log_level = get_entity_id("log_level", default="info")


# Create a color formatter
formatter = colorlog.ColoredFormatter(
    "%(log_color)s%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    log_colors={
        'DEBUG':    'cyan',
        'INFO':     'green',
        'WARNING':  'yellow',
        'ERROR':    'red',
        'CRITICAL': 'bold_red',
    }
)
# Create a handler
handler = logging.StreamHandler()
handler.setFormatter(formatter)


LOG_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

logger_level = LOG_LEVELS.get(configured_log_level.lower(), logging.INFO)

# Set up the logger
logger = colorlog.getLogger()
logger.addHandler(handler)
logger.setLevel(logger_level)


# Configure logging with timestamps without milliseconds
logging.basicConfig(
    level=logger_level,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"  # <- remove milliseconds
)
logger = logging.getLogger(__name__)

# Silence logger spam
logging.getLogger("ha_mqtt_discoverable").setLevel(logging.WARNING)
logging.getLogger("ha_mqtt_discoverable.sensors").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)