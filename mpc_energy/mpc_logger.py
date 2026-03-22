import logging
import colorlog

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

# Set up the logger
logger = colorlog.getLogger()
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)


# Configure logging with timestamps without milliseconds
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"  # <- remove milliseconds
)
logger = logging.getLogger(__name__)

# Silence logger spam
logging.getLogger("ha_mqtt_discoverable").setLevel(logging.WARNING)
logging.getLogger("ha_mqtt_discoverable.sensors").setLevel(logging.WARNING)
logging.getLogger("matplotlib.font_manager").setLevel(logging.WARNING)