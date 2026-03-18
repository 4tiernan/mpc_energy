class MPCEnergyError(Exception):
    """Base exception for expected, user-facing MPC Energy failures."""

class HAAPIError(MPCEnergyError):
     """HA API Authentication Error"""

class HAAPIAuthenticationError(MPCEnergyError):
     """HA API Authentication Error"""

class AmberAPIError(MPCEnergyError):
    """Base exception for Amber API failures."""


class AmberAPITimeoutError(AmberAPIError):
    """Raised when an Amber API request times out."""


class AmberAPIConnectionError(AmberAPIError):
    """Raised when a connection to the Amber API cannot be established."""


class AmberAPIRequestError(AmberAPIError):
    """Raised for other Amber API request failures."""
