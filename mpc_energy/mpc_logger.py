import logging
import colorlog

import config_manager

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


configured_log_level = config_manager.log_level  # e.g. "debug"

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