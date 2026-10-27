"""Tests for the probe ladder.

The machine is off most of the day, so this is the behaviour that matters most:
how long the integration waits between probes, and how quickly it notices that
the printer came back.
"""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.exceptions import ConfigEntryError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zmorph.client import ZMorphProtocolError
from custom_components.zmorph.coordinator import (
    ZMorphCoordinator,
    human_interval,
    next_interval,
    probe_limits,
)

from .conftest import make_entry, state_of
from .const import IDLE_STATUS, ONLINE_STATUS, TEST_HOST

# 15s doubling: 15, 30, 60, 120, 240, 480, 960, then the 1200s ceiling.
LADDER = [15, 30, 60, 120, 240, 480, 960, 1200, 1200, 1200]


@pytest.mark.parametrize(
    ("silent_probes", "expected"), list(enumerate(LADDER, start=1))
)
def test_the_wait_doubles_until_it_reaches_the_ceiling(
    silent_probes: int, expected: int
) -> None:
    """Each silent probe doubles the wait, and it stops at the maximum."""
    interval = next_interval(
        timedelta(seconds=15), silent_probes, timedelta(seconds=1200)
    )

    assert interval == timedelta(seconds=expected)


def test_the_wait_never_drops_below_the_minimum() -> None:
    """Zero silent probes means the machine answered: probe at the minimum."""
    interval = next_interval(timedelta(seconds=15), 0, timedelta(seconds=1200))

    assert interval == timedelta(seconds=15)


def test_the_ceiling_can_be_smaller_than_one_doubling() -> None:
    """A short ceiling is respected, not overshot by the doubling."""
    interval = next_interval(timedelta(seconds=15), 3, timedelta(seconds=20))

    assert interval == timedelta(seconds=20)


async def test_silent_probes_stretch_the_interval(
    hass, offline_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Every round that reaches nothing moves the next probe further out."""
    coordinator: ZMorphCoordinator = offline_entry.runtime_data

    # The round that set the entry up already reached nothing, so the ladder is at
    # its first step: the starting wait, not a doubled one.
    assert coordinator.probe_interval == timedelta(seconds=15)
    assert coordinator.silent_probes == 1

    for expected in [30, 60, 120, 240]:
        await coordinator.async_refresh()
        assert coordinator.probe_interval == timedelta(seconds=expected)

    assert coordinator.silent_probes == 5
    assert coordinator.data.online is False
    assert coordinator.data.state.value == "offline"


async def test_answering_puts_the_interval_back_to_the_minimum(
    hass, offline_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The machine wakes up: the wait drops straight back to 15 seconds."""
    coordinator: ZMorphCoordinator = offline_entry.runtime_data

    await coordinator.async_refresh()
    await coordinator.async_refresh()
    assert coordinator.probe_interval == timedelta(seconds=60)

    mock_client.probe.side_effect = None
    mock_client.probe.return_value = ONLINE_STATUS

    await coordinator.async_refresh()

    assert coordinator.probe_interval == coordinator.min_interval
    assert coordinator.silent_probes == 0
    assert coordinator.data.online is True


async def test_the_probe_time_is_recorded(hass, loaded_entry: MockConfigEntry) -> None:
    """The next probe time is exposed, so the ladder is visible to the user."""
    coordinator: ZMorphCoordinator = loaded_entry.runtime_data

    assert coordinator.next_probe is not None
    remaining = coordinator.next_probe - coordinator.next_probe.now(
        coordinator.next_probe.tzinfo
    )
    assert timedelta(0) < remaining <= timedelta(seconds=15)


async def test_probe_now_ignores_the_waiting_time(
    hass, offline_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The button probes immediately, whatever the ladder was waiting for."""
    coordinator: ZMorphCoordinator = offline_entry.runtime_data

    for _ in range(4):
        await coordinator.async_refresh()
    assert coordinator.probe_interval == timedelta(seconds=240)
    mock_client.probe.reset_mock()

    await coordinator.async_probe_now()

    mock_client.probe.assert_awaited_once()
    # Still off, so the ladder starts again from the bottom instead of going on
    # from 480 seconds.
    assert coordinator.silent_probes == 1
    assert coordinator.probe_interval == timedelta(seconds=15)


async def test_probe_now_reports_a_machine_that_came_back(
    hass, offline_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Forcing a probe after switching the machine on shows the readings at once."""
    coordinator: ZMorphCoordinator = offline_entry.runtime_data
    mock_client.probe.side_effect = None
    mock_client.probe.return_value = IDLE_STATUS

    await coordinator.async_probe_now()

    assert coordinator.data.online is True
    assert coordinator.data.state.value == "idle"
    assert coordinator.silent_probes == 0


async def test_a_wrong_address_is_reported_as_an_error(
    hass, loaded_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Something that answers with non-G-code is a configuration problem."""
    coordinator: ZMorphCoordinator = loaded_entry.runtime_data
    mock_client.probe.side_effect = ZMorphProtocolError(TEST_HOST, "'<html>'")

    await coordinator.async_refresh()

    assert coordinator.last_update_success is False
    assert coordinator.last_exception is not None
    assert "not_a_zmorph" in str(
        getattr(coordinator.last_exception, "translation_key", "")
    )
    assert loaded_entry.state is ConfigEntryState.LOADED


async def test_polling_disabled_hides_the_next_probe_time(
    hass, loaded_entry: MockConfigEntry
) -> None:
    """With polling off there is no next probe, so the entity has no value."""
    coordinator: ZMorphCoordinator = loaded_entry.runtime_data

    hass.config_entries.async_update_entry(loaded_entry, pref_disable_polling=True)
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.next_probe is None
    assert state_of(hass, "sensor.fab_next_probe").state == "unknown"


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({}, (15, 1200)),
        ({"min_probe_interval": 30, "max_probe_interval": 600}, (30, 600)),
        ({"min_probe_interval": "45", "max_probe_interval": "900"}, (45, 900)),
        ({"min_probe_interval": None, "max_probe_interval": "junk"}, (15, 1200)),
    ],
)
def test_the_limits_come_from_the_options(
    hass, options: dict[str, object], expected: tuple[int, int]
) -> None:
    """The configured ladder is read from the entry options."""
    minimum, maximum = probe_limits(make_entry(options=dict(options)))

    assert (int(minimum.total_seconds()), int(maximum.total_seconds())) == expected


def test_a_ladder_the_wrong_way_round_stops_setup(hass) -> None:
    """A maximum below the minimum cannot work, and says so."""
    entry = make_entry(options={"min_probe_interval": 600, "max_probe_interval": 60})

    with pytest.raises(ConfigEntryError) as err:
        probe_limits(entry)

    assert err.value.translation_key == "max_below_min_probe_interval"


def test_an_out_of_range_minimum_stops_setup(hass) -> None:
    """A wait below five seconds would hammer the machine."""
    entry = make_entry(options={"min_probe_interval": 1, "max_probe_interval": 600})

    with pytest.raises(ConfigEntryError) as err:
        probe_limits(entry)

    assert err.value.translation_key == "invalid_probe_interval"


def test_a_machine_that_never_answered_starts_offline(
    hass, offline_entry: MockConfigEntry
) -> None:
    """Setup succeeds with the printer off, and the state entity says offline."""
    assert offline_entry.state is ConfigEntryState.LOADED
    assert state_of(hass, "sensor.fab_state").state == "offline"

    # The measurements have nothing true to show.
    assert state_of(hass, "sensor.fab_nozzle_temperature").state == STATE_UNAVAILABLE
    assert state_of(hass, "sensor.fab_progress").state == STATE_UNAVAILABLE

    # The button that ends the waiting stays usable while the machine is off.
    assert state_of(hass, "button.fab_probe_now").state == "unknown"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(45, "45 seconds"), (120, "2 minutes"), (900, "15 minutes"), (7200, "2.0 hours")],
)
def test_intervals_are_logged_the_way_a_person_reads_them(
    seconds: int, expected: str
) -> None:
    """The log line says how long the wait is, in the unit it is written in."""
    assert human_interval(timedelta(seconds=seconds)) == expected


def test_human_interval_of_nothing_at_all() -> None:
    """A disabled schedule has no next probe."""
    assert human_interval(None) == "never"


def test_coordinator_falls_back_to_the_address_without_a_unique_id(
    hass, mock_client: AsyncMock
) -> None:
    """An entry without a unique id is still identified by its address."""
    entry = MockConfigEntry(
        domain="zmorph",
        unique_id=None,
        title="fab",
        data={"host": TEST_HOST, "port": 80},
    )
    entry.add_to_hass(hass)

    coordinator = ZMorphCoordinator(hass, entry, mock_client)

    assert coordinator.machine_id == f"{TEST_HOST}:80"
    assert coordinator.min_interval == timedelta(seconds=15)
    assert coordinator.max_interval == timedelta(seconds=1200)
