"""Constants for Home Print."""

from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SSL,
    CONF_VERIFY_SSL,
)

DOMAIN = "home_print"

DEFAULT_PORT = 631
DEFAULT_PATH = "/ipp/print"
DEFAULT_MAX_FILE_MB = 25
DEFAULT_SCAN_INTERVAL = 60
# Seconds allowed for a whole Print-Job upload; slow inkjets may need to wake.
PRINT_TIMEOUT = 300

EVENT_JOB = "home_print_job"

CONF_BASE_PATH = "base_path"
CONF_MAX_FILE_MB = "max_file_mb"
CONF_ADMIN_ONLY = "admin_only"
CONF_DEFAULT_SIDES = "default_sides"
CONF_DEFAULT_COLOR_MODE = "default_color_mode"

__all__ = [
    "CONF_ADMIN_ONLY",
    "CONF_BASE_PATH",
    "CONF_DEFAULT_COLOR_MODE",
    "CONF_DEFAULT_SIDES",
    "CONF_HOST",
    "CONF_MAX_FILE_MB",
    "CONF_PORT",
    "CONF_SCAN_INTERVAL",
    "CONF_SSL",
    "CONF_VERIFY_SSL",
    "DEFAULT_MAX_FILE_MB",
    "DEFAULT_PATH",
    "DEFAULT_PORT",
    "DEFAULT_SCAN_INTERVAL",
    "DOMAIN",
    "EVENT_JOB",
    "PRINT_TIMEOUT",
]
