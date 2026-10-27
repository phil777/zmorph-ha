"""Tests for the Zmorph sensors."""

from unittest.mock import AsyncMock

import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import (
    PERCENTAGE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zmorph.sensor import SENSORS

from .conftest import state_of
from .const import EXPECTED_PROGRESS, TEST_UNIQUE_ID

# The entities a user sees without touching anything, and the sample values.
ENABLED_STATES = {
    "sensor.fab_state": "printing",
    "sensor.fab_progress": str(EXPECTED_PROGRESS),
    "sensor.fab_nozzle_temperature": "189.9",
    "sensor.fab_nozzle_target": "190.0",
    "sensor.fab_bed_temperature": "60.0",
    "sensor.fab_bed_target": "60.0",
}

# The ones that are there for debugging a machine, off until asked for.
DISABLED_BY_DEFAULT = {
    "position_x",
    "position_y",
    "position_z",
    "bytes_printed",
    "bytes_total",
    "probe_interval",
}


@pytest.mark.parametrize(("entity_id", "expected"), ENABLED_STATES.items())
async def test_the_readings_of_an_answering_machine(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, entity_id: str, expected: str
) -> None:
    """Every G-code answer shows up as the value of its entity."""
    state = state_of(hass, entity_id)

    assert state.state == expected


async def test_progress_is_the_share_of_the_file(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """24758 of 968376 bytes is 2.6 percent, and that is what progress says."""
    state = state_of(hass, "sensor.fab_progress")

    assert state.state == str(EXPECTED_PROGRESS)
    assert state.attributes["unit_of_measurement"] == PERCENTAGE


async def test_progress_has_no_invented_time_left(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """The firmware gives no ETA, so no ETA is published."""
    attributes = state_of(hass, "sensor.fab_progress").attributes

    for guess in ("finish_at", "eta", "remaining_time", "estimated_time"):
        assert guess not in attributes


async def test_the_idle_machine_has_no_progress(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """With no job there are no bytes to divide, so progress says unknown."""
    from .const import IDLE_STATUS

    mock_client.probe.return_value = IDLE_STATUS
    await loaded_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert state_of(hass, "sensor.fab_state").state == "idle"
    # The machine answered, so the entity is available: there is simply no
    # percentage to show without a job.
    assert state_of(hass, "sensor.fab_progress").state == STATE_UNKNOWN


async def test_an_off_machine_shows_offline_not_stale_numbers(
    hass: HomeAssistant, offline_entry: MockConfigEntry
) -> None:
    """Offline is a state; the measurements that would be stale go away."""
    assert state_of(hass, "sensor.fab_state").state == "offline"
    assert state_of(hass, "sensor.fab_state").attributes["friendly_name"] == "fab State"

    for entity_id in ("sensor.fab_nozzle_temperature", "sensor.fab_progress"):
        assert state_of(hass, entity_id).state == STATE_UNAVAILABLE, entity_id


async def test_the_next_probe_time_is_shown_while_offline(
    hass: HomeAssistant, offline_entry: MockConfigEntry
) -> None:
    """The wait itself is a fact about the integration, so it stays visible."""
    state = hass.states.get("sensor.fab_next_probe")

    assert state is not None
    assert state.state != STATE_UNAVAILABLE
    assert state.attributes["device_class"] == SensorDeviceClass.TIMESTAMP
    assert state.attributes["silent_probes"] >= 1


async def test_the_ladder_entities_describe_the_integration(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """The state and the next-probe entities do not need the machine to answer."""
    registry = er.async_get(hass)
    descriptions = {description.key: description for description in SENSORS}

    for key in ("state", "next_probe"):
        entry = registry.async_get_entity_id(
            "sensor", "zmorph", f"{TEST_UNIQUE_ID}_{key}"
        )
        assert entry is not None, f"{key} is missing from the registry"
        assert descriptions[key].reads_the_machine is False


async def test_the_debug_entities_start_switched_off(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Positions and byte counts exist, but do not clutter a fresh install."""
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, loaded_entry.entry_id)
    by_unique = {entry.unique_id: entry for entry in entries}

    for key in DISABLED_BY_DEFAULT:
        registry_entry = by_unique[f"{TEST_UNIQUE_ID}_{key}"]
        assert registry_entry.disabled, f"{key} should start disabled"
        assert hass.states.get(registry_entry.entity_id) is None


async def test_a_switched_on_debug_entity_shows_its_value(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Enabling the Z position reveals the answer of M114."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", "zmorph", f"{TEST_UNIQUE_ID}_position_z"
    )
    assert entity_id is not None
    registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "0.2"
    assert state.attributes["unit_of_measurement"] == "mm"


async def test_every_description_becomes_exactly_one_entity(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """No description is added twice and none is missed."""
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, loaded_entry.entry_id)
    sensor_ids = {
        entry.unique_id for entry in entries if entry.entity_id.startswith("sensor.")
    }

    assert sensor_ids == {
        f"{TEST_UNIQUE_ID}_{description.key}" for description in SENSORS
    }


async def test_names_and_icons_come_from_the_translation_files(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """The friendly name is the device name plus the translated entity name."""
    entity = state_of(hass, "sensor.fab_nozzle_temperature")

    assert entity.attributes["friendly_name"] == "fab Nozzle temperature"
    assert entity.attributes["device_class"] == SensorDeviceClass.TEMPERATURE
    assert entity.attributes["unit_of_measurement"] == UnitOfTemperature.CELSIUS
