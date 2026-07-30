"""
config — Configuration management for the NYX client.
"""

from nyx_client.config.defaults import (
    CONFIG_PATH,
    DEFAULT_CONFIG,
    LOCAL_DB_PATH,
    NYX_HOME,
    VERSION,
)
from nyx_client.config.settings import NYXConfig

__all__ = [
    "VERSION",
    "NYX_HOME",
    "CONFIG_PATH",
    "LOCAL_DB_PATH",
    "DEFAULT_CONFIG",
    "NYXConfig",
]