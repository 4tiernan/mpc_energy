
DOMAIN = "mpc_energy"
DEFAULT_NAME = "MPC Energy"

# Required entities from homeassistant:
class PlantEntites():
    BATTERY_DISCHARGE_COST = "Battery Discharge Cost ($/kWh)"
    HA_EMS_CONTROL_SWITCH = "EMS Controlled By Home Assistant Switch (switch)"
    EMS_CONTROL_MODE = "EMS Control Mode (dropdown)"
    DISCHARGE_LIMITER = "Discharge Limiter (number input)"
    CHARGE_LIMITER = "Charge Limiter (number input)"
    PV_LIMTER = "PV Limiter (number input)"
    EXPORT_LIMITER = "Export Limiter (number input)"
    IMPORT_LIMTER = "Import Limiter (number input)"

    BATTERY_RATED_CAPACITY = "Battery Rated Capacity (kWh)"
    BACKUP_SOC = "Backup Buffer SOC (%)"
    CHARGE_CUTOFF_SOC = "Charge Cut-Off SOC (%)"
    BATTERY_SOC = "Battery SOC (%)"

    CHARGE_LIMIT = "Battery Charge Power Limit (kW)"
    DISCHARGE_LIMIT = "Battery Discharge Power Limit (kW)"
    PV_LIMIT = "Solar MPPT DC Power Limit (kW)"
    INVERTER_LIMIT = "Inverter AC Power Limit (kW)"
    IMPORT_LIMIT = "Grid Import Power Limit (kW)"
    EXPORT_LIMIT = "Grid Export Power Limit (kW)"

    LOAD_POWER = "Load Power (kW)"
    SOLAR_POWER = "Solar Power (kW)"
    BATTERY_POWER = "Battery Power (kW)(+dis, -chg)"
    INVERTER_POWER = "Inverter Power (kW)(+generating, -consuming)"
    GRID_POWER = "Grid Power (kW)(-export, +import)"

    SOLCAST_FORECAST = "Solcast Solar Forecast Today (kWh)"

