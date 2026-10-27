"""Constants for the Zmorph integration."""

from logging import Logger, getLogger
from typing import Final

from homeassistant.const import Platform

LOGGER: Logger = getLogger(__package__)

DOMAIN: Final = "zmorph"
MANUFACTURER: Final = "Zmorph S.A."
MODEL: Final = "Zmorph Fab"

PLATFORMS: Final[list[Platform]] = [Platform.BUTTON, Platform.SENSOR]

# The machine answers G-code over plain HTTP. Its name is normally the DNS name
# of the printer on the local network.
DEFAULT_HOST: Final = "fab"
DEFAULT_PORT: Final = 80
COMMAND_PATH: Final = "/command"

# One G-code per request. A request slower than this is a machine that has
# already gone away, so give up and let the probe ladder wait instead.
REQUEST_TIMEOUT: Final = 5

# Probing a machine that is off is the normal state, so the wait between probes
# doubles every time the machine stays silent, and drops back to the minimum the
# moment it answers. Both ends of the ladder are configurable per entry.
CONF_MIN_PROBE_INTERVAL: Final = "min_probe_interval"
CONF_MAX_PROBE_INTERVAL: Final = "max_probe_interval"

DEFAULT_MIN_PROBE_INTERVAL: Final = 15
DEFAULT_MAX_PROBE_INTERVAL: Final = 1200

MIN_PROBE_INTERVAL_LIMIT: Final = 5
MAX_PROBE_INTERVAL_LIMIT: Final = 86400

# 15s -> 30s -> 60s -> 120s -> 240s -> 480s -> 960s -> 1200s (capped)
PROBE_BACKOFF_FACTOR: Final = 2.0
