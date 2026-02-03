from const import (
    DOMAIN,
    DEFAULT_NAME
)

##### LOGGGING !!!!!!!

def setup(hass, config):
    hass.states.set("mpc_energy.effective_price", "31")
    
    return True # True lets HA know the integration setup succesfully.