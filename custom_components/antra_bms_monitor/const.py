"""Constants for the Antra BMS integration.""" 
from __future__ import annotations

DOMAIN = "antra_bms_monitor"
CONF_BAUD_RATE = "baud_rate"
CONF_MAX_BATTERIES = "max_batteries"
DEFAULT_BAUD_RATE = 9600
DEFAULT_MAX_BATTERIES = 4
PLATFORMS = ["sensor"]