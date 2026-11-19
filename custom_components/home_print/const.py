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
# Extra seconds per page sent for converted (raster) jobs: the printer reads
# the upload only as fast as it prints.
PRINT_TIMEOUT_PER_PAGE = 15

EVENT_JOB = "home_print_job"
EVENT_SCAN = "home_print_scan"

CONF_BASE_PATH = "base_path"
CONF_MAX_FILE_MB = "max_file_mb"
CONF_ADMIN_ONLY = "admin_only"
CONF_DEFAULT_SIDES = "default_sides"
CONF_DEFAULT_COLOR_MODE = "default_color_mode"
# Days a printed file (and its record) is kept; 0 keeps no files.
CONF_HISTORY_DAYS = "history_days"
DEFAULT_HISTORY_DAYS = 7
MAX_HISTORY_DAYS = 90
# Days a scan (and its record) is kept in the media folder; 0 keeps it forever.
CONF_SCAN_DAYS = "scan_days"
DEFAULT_SCAN_DAYS = 30
MAX_SCAN_DAYS = 3650
MAX_SCAN_MB = 100000
# Total size of archived scans in MB; oldest go first when exceeded; 0 = no cap.
CONF_SCAN_MAX_MB = "scan_max_mb"
DEFAULT_SCAN_MAX_MB = 2000
CONF_SCANNER_URL = "scanner_url"
# Entry data. "kind" is "printer" (default, also for entries made before it
# existed) or "scanner" for a scanner without a printer.
CONF_KIND = "kind"
KIND_PRINTER = "printer"
KIND_SCANNER = "scanner"
# The eSCL base URL a scanner announced over zeroconf (_uscan/_uscans), or
# where a scanner-only entry lives.
CONF_SCANNER_ANNOUNCED = "scanner_announced_url"
# The scanner's zeroconf TXT record, for diagnostics.
CONF_SCANNER_TXT = "scanner_txt"

__all__ = [
    "CONF_ADMIN_ONLY",
    "CONF_BASE_PATH",
    "CONF_DEFAULT_COLOR_MODE",
    "CONF_DEFAULT_SIDES",
    "CONF_HISTORY_DAYS",
    "CONF_HOST",
    "CONF_KIND",
    "CONF_MAX_FILE_MB",
    "CONF_PORT",
    "CONF_SCANNER_ANNOUNCED",
    "CONF_SCANNER_TXT",
    "CONF_SCANNER_URL",
    "CONF_SCAN_DAYS",
    "CONF_SCAN_INTERVAL",
    "CONF_SCAN_MAX_MB",
    "CONF_SSL",
    "CONF_VERIFY_SSL",
    "DEFAULT_HISTORY_DAYS",
    "DEFAULT_MAX_FILE_MB",
    "DEFAULT_PATH",
    "DEFAULT_PORT",
    "DEFAULT_SCAN_DAYS",
    "DEFAULT_SCAN_INTERVAL",
    "DEFAULT_SCAN_MAX_MB",
    "DOMAIN",
    "EVENT_JOB",
    "EVENT_SCAN",
    "KIND_PRINTER",
    "KIND_SCANNER",
    "MAX_HISTORY_DAYS",
    "MAX_SCAN_DAYS",
    "MAX_SCAN_MB",
    "PRINT_TIMEOUT",
    "PRINT_TIMEOUT_PER_PAGE",
]
