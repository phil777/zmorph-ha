"""Coordinator for the Zmorph integration.

The machine is switched off most of the day, so a fixed polling rate is wrong in
both directions: too chatty against a host that is not there, too slow to notice
a job that just started. The coordinator therefore walks an interval:

    15s -> 30s -> 60s -> 120s -> 240s -> ... -> 20min   every silent probe
    anything -> 15s                                     the first probe that answers

Both ends of the ladder are options of the config entry. A manual probe puts the
ladder back at the bottom, so someone who just switched the machine on does not
wait for it.
"""

from datetime import datetime, timedelta
from typing import override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import ZMorphClient, ZMorphOffline, ZMorphProtocolError
from .const import (
    CONF_MAX_PROBE_INTERVAL,
    CONF_MIN_PROBE_INTERVAL,
    DEFAULT_MAX_PROBE_INTERVAL,
    DEFAULT_MIN_PROBE_INTERVAL,
    DOMAIN,
    LOGGER,
    MAX_PROBE_INTERVAL_LIMIT,
    MIN_PROBE_INTERVAL_LIMIT,
    PROBE_BACKOFF_FACTOR,
)
from .models import ZMorphIdentity, ZMorphStatus, offline_status

type ZMorphConfigEntry = ConfigEntry[ZMorphCoordinator]


class ZMorphCoordinator(DataUpdateCoordinator[ZMorphStatus]):
    """Probe one machine, with an interval that grows while it stays silent."""

    config_entry: ZMorphConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ZMorphConfigEntry,
        client: ZMorphClient,
    ) -> None:
        """Initialize the coordinator."""
        self.client = client
        self.identity = ZMorphIdentity()
        # The id is chosen once, in the config flow, and stays: entity ids are
        # built on it, and a machine that changes its name or starts reporting a
        # UUID must not lose the entries a user has already put on dashboards.
        self.machine_id = config_entry.unique_id or client.machine_key
        self._min_interval, self._max_interval = probe_limits(config_entry)
        self.silent_probes = 0
        self.next_probe: datetime | None = None

        super().__init__(
            hass,
            logger=LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            # Bottom of the ladder. A machine that is on answers on the first try.
            update_interval=self._min_interval,
        )

    @property
    def min_interval(self) -> timedelta:
        """Return the interval used while the machine answers."""
        return self._min_interval

    @property
    def max_interval(self) -> timedelta:
        """Return the longest interval the ladder stops at."""
        return self._max_interval

    @property
    def probe_interval(self) -> timedelta:
        """Return the wait the next probe is scheduled for."""
        return self.update_interval or self._min_interval

    @property
    def awake(self) -> bool:
        """Return whether the machine answered the last probe."""
        return bool(self.data and self.data.online)

    @override
    async def _async_setup(self) -> None:
        """Read the firmware identity, if the machine happens to be awake.

        The identity is a nice to have: it names the firmware and may give a UUID.
        Nothing here depends on it, so an off machine, or a firmware that answers
        M115 in some unexpected way, must not stop setup.
        """
        try:
            self.identity = await self.client.fetch_identity()
        except Exception as err:
            LOGGER.debug("%s gave no usable identity: %s", self.client.host, err)

    @override
    async def _async_update_data(self) -> ZMorphStatus:
        """Send one round of G-code and collect every answer.

        A machine that does not answer is not a failure: the snapshot says
        offline, the interval grows, and nothing is logged above debug. Only a
        host that answers with something other than controller output is reported
        as an error, because that needs the user to change the configuration.
        """
        try:
            status = await self.client.probe()
        except ZMorphOffline as err:
            self._note_silent_probe()
            return offline_status(self.data, str(err))
        except ZMorphProtocolError as err:
            self._note_silent_probe()
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="not_a_zmorph",
                translation_placeholders={"host": self.client.host},
            ) from err

        self._note_answer()
        return status

    async def async_probe_now(self) -> None:
        """Probe right now, then carry on from the bottom of the ladder.

        This is what the Probe now button and the ``zmorph.probe`` service call.
        """
        self.silent_probes = 0
        self.update_interval = self._min_interval
        await self.async_refresh()

    def _note_silent_probe(self) -> None:
        """Stretch the wait after a probe that reached nothing."""
        self.silent_probes += 1
        self.update_interval = next_interval(
            self._min_interval, self.silent_probes, self._max_interval
        )

        if self.silent_probes == 1:
            LOGGER.info(
                "%s is not answering; next probe in %s",
                self.client.host,
                human_interval(self.update_interval),
            )
        else:
            LOGGER.debug(
                "%s still silent after %d probes; next probe in %s",
                self.client.host,
                self.silent_probes,
                human_interval(self.update_interval),
            )
        self._mark_next_probe()

    def _note_answer(self) -> None:
        """Put the wait back at the minimum after the machine answered."""
        if self.silent_probes:
            LOGGER.info(
                "%s answered after %d silent probe(s); probing every %s again",
                self.client.host,
                self.silent_probes,
                human_interval(self._min_interval),
            )
        self.silent_probes = 0
        self.update_interval = self._min_interval
        self._mark_next_probe()

    def _mark_next_probe(self) -> None:
        """Record when the next probe is due, for the sensor and diagnostics."""
        if self.config_entry.pref_disable_polling:
            self.next_probe = None
            return
        self.next_probe = dt_util.utcnow() + self.probe_interval


def next_interval(
    minimum: timedelta, silent_probes: int, maximum: timedelta
) -> timedelta:
    """Return the wait after ``silent_probes`` probes reached nothing."""
    growth = PROBE_BACKOFF_FACTOR ** max(silent_probes - 1, 0)
    return min(timedelta(seconds=minimum.total_seconds() * growth), maximum)


def probe_limits(config_entry: ConfigEntry) -> tuple[timedelta, timedelta]:
    """Return the configured probe ladder, in seconds.

    Raises:
        ConfigEntryError: an option is out of range, or the maximum is shorter
            than the minimum. Home Assistant shows the reason on the entry.
    """
    minimum = _seconds(
        config_entry.options.get(CONF_MIN_PROBE_INTERVAL), DEFAULT_MIN_PROBE_INTERVAL
    )
    maximum = _seconds(
        config_entry.options.get(CONF_MAX_PROBE_INTERVAL), DEFAULT_MAX_PROBE_INTERVAL
    )

    if not MIN_PROBE_INTERVAL_LIMIT <= minimum <= MAX_PROBE_INTERVAL_LIMIT:
        raise ConfigEntryError(
            f"The minimum probe interval must be between {MIN_PROBE_INTERVAL_LIMIT} "
            f"and {MAX_PROBE_INTERVAL_LIMIT} seconds",
            translation_domain=DOMAIN,
            translation_key="invalid_probe_interval",
        )
    if maximum < minimum:
        raise ConfigEntryError(
            "The maximum probe interval must not be shorter than the minimum",
            translation_domain=DOMAIN,
            translation_key="max_below_min_probe_interval",
        )

    return timedelta(seconds=minimum), timedelta(seconds=maximum)


def _seconds(value: object, default: int) -> int:
    """Return an option as whole seconds, or the default when it is not a number.

    An option that is missing, blank, or not a number falls back to the default
    instead of failing: the ladder still has to run.
    """
    try:
        return int(float(str(value)))
    except TypeError, ValueError:
        return default


def human_interval(interval: timedelta | None) -> str:
    """Return an interval as seconds, minutes or hours, for a log line."""
    if interval is None:
        return "never"
    seconds = int(interval.total_seconds())
    if seconds < 120:
        return f"{seconds} seconds"
    minutes = round(seconds / 60)
    if minutes < 120:
        return f"{minutes} minutes"
    return f"{round(seconds / 3600, 1)} hours"
