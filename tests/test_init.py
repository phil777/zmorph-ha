"""Tests for setting the integration up, including with the printer switched off."""

from unittest.mock import AsyncMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zmorph.client import ZMorphOffline, ZMorphProtocolError
from custom_components.zmorph.coordinator import ZMorphCoordinator

from .conftest import make_entry, state_of
from .const import TEST_HOST, TEST_PORT, TEST_UNIQUE_ID

# One entity per platform proves the entry was forwarded to both of them.
MACHINE_ENTITIES = (
    "sensor.fab_state",
    "sensor.fab_progress",
    "sensor.fab_nozzle_temperature",
    "sensor.fab_nozzle_target",
    "sensor.fab_bed_temperature",
    "sensor.fab_bed_target",
    "button.fab_probe_now",
)


async def test_a_machine_that_answers_sets_up_every_entity(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """The entry loads, the coordinator lands in runtime_data, entities appear."""
    assert loaded_entry.state is ConfigEntryState.LOADED
    assert isinstance(loaded_entry.runtime_data, ZMorphCoordinator)
    assert loaded_entry.runtime_data.machine_id == TEST_UNIQUE_ID

    for entity_id in MACHINE_ENTITIES:
        assert hass.states.get(entity_id) is not None, f"{entity_id} is missing"


async def test_unload_and_load_again(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """The entry can be reloaded without restarting Home Assistant."""
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    await hass.async_block_till_done()

    assert loaded_entry.state is ConfigEntryState.NOT_LOADED
    assert not hasattr(loaded_entry, "runtime_data")


async def test_an_off_machine_is_a_working_setup(
    hass: HomeAssistant, offline_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Switched off is the normal state, so setup succeeds and says offline."""
    assert offline_entry.state is ConfigEntryState.LOADED

    assert state_of(hass, "sensor.fab_state").state == "offline"
    assert state_of(hass, "button.fab_probe_now").state != STATE_UNAVAILABLE
    assert state_of(hass, "sensor.fab_next_probe").state != STATE_UNAVAILABLE


async def test_an_off_machine_hides_the_measurements(
    hass: HomeAssistant, offline_entry: MockConfigEntry
) -> None:
    """Nothing is invented while the printer is off: the readings go away."""
    for entity_id in (
        "sensor.fab_progress",
        "sensor.fab_nozzle_temperature",
        "sensor.fab_nozzle_target",
        "sensor.fab_bed_temperature",
        "sensor.fab_bed_target",
    ):
        assert state_of(hass, entity_id).state == STATE_UNAVAILABLE, entity_id


async def test_the_machine_coming_back_is_picked_up(
    hass: HomeAssistant, offline_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Switching the printer on turns the offline entities back into readings."""
    assert state_of(hass, "sensor.fab_state").state == "offline"

    from .const import ONLINE_STATUS

    mock_client.probe.side_effect = None
    mock_client.probe.return_value = ONLINE_STATUS
    await offline_entry.runtime_data.async_probe_now()
    await hass.async_block_till_done()

    assert state_of(hass, "sensor.fab_state").state == "printing"
    assert state_of(hass, "sensor.fab_progress").state == "2.6"


async def test_a_host_that_is_not_the_machine_retries(
    hass: HomeAssistant, mock_client: AsyncMock
) -> None:
    """A wrong address is retried, and the entry says why it is not ready."""
    mock_client.probe.side_effect = ZMorphProtocolError(TEST_HOST, "'<html>'")
    entry = make_entry()
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_a_ladder_the_wrong_way_round_stops_the_entry(
    hass: HomeAssistant, mock_client: AsyncMock
) -> None:
    """A maximum below the minimum is a configuration error, not an offline printer."""
    entry = make_entry(options={"min_probe_interval": 600, "max_probe_interval": 60})
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert "maximum probe interval" in entry.reason


async def test_an_unreachable_machine_at_setup_is_not_an_error(
    hass: HomeAssistant, mock_client: AsyncMock
) -> None:
    """Adding a printer that is off gives a loaded entry, not a failed one."""
    mock_client.probe.side_effect = ZMorphOffline(TEST_HOST, "refused the connection")
    entry = make_entry(host=TEST_HOST, port=TEST_PORT)
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
