"""Tests for the Probe now button and the diagnostics report."""

from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zmorph.diagnostics import async_get_config_entry_diagnostics

from .conftest import state_of
from .const import IDENTITY, TEST_UNIQUE_ID

PROBE_BUTTON = "button.fab_probe_now"


async def test_the_button_exists_and_is_diagnostic(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """The one button of this integration forces a probe."""
    state = hass.states.get(PROBE_BUTTON)
    assert state is not None
    assert state.attributes["friendly_name"] == "fab Probe now"

    # The category lives in the registry, not in the state.
    registry = er.async_get(hass)
    registry_entry = registry.async_get(PROBE_BUTTON)
    assert registry_entry is not None
    assert registry_entry.entity_category == EntityCategory.DIAGNOSTIC


async def test_pressing_the_button_probes_the_machine(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A press sends the round now instead of waiting for the ladder."""
    mock_client.probe.reset_mock()

    await hass.services.async_call(
        "button", "press", {"entity_id": PROBE_BUTTON}, blocking=True
    )

    mock_client.probe.assert_awaited_once()


async def test_pressing_the_button_while_the_machine_is_off_works(
    hass: HomeAssistant, offline_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The button has to be usable exactly when the printer is not answering."""
    assert state_of(hass, PROBE_BUTTON).state != STATE_UNAVAILABLE
    mock_client.probe.reset_mock()

    await hass.services.async_call(
        "button", "press", {"entity_id": PROBE_BUTTON}, blocking=True
    )
    await hass.async_block_till_done()

    mock_client.probe.assert_awaited_once()


async def test_pressing_the_button_shortens_a_long_wait(
    hass: HomeAssistant, offline_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """After the ladder stretched, a press brings the next probe back close."""
    coordinator = offline_entry.runtime_data
    for _ in range(5):
        await coordinator.async_refresh()
    assert coordinator.probe_interval.total_seconds() > 60

    await hass.services.async_call(
        "button", "press", {"entity_id": PROBE_BUTTON}, blocking=True
    )

    # Reset to the start of the ladder, then one silent probe on top.
    assert coordinator.silent_probes == 1
    assert coordinator.probe_interval == coordinator.min_interval


async def test_a_press_that_finds_nothing_reports_no_failure(
    hass: HomeAssistant, offline_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The machine being off is not an error, so the press simply completes."""
    await hass.services.async_call(
        "button", "press", {"entity_id": PROBE_BUTTON}, blocking=True
    )
    await hass.async_block_till_done()

    assert offline_entry.state is ConfigEntryState.LOADED


async def test_diagnostics_carry_the_raw_gcode_answers(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """The raw text of a round is what makes a firmware problem reportable."""
    diagnostics = await async_get_config_entry_diagnostics(hass, loaded_entry)

    assert diagnostics["config_entry_id"] == loaded_entry.entry_id
    assert diagnostics["config_entry_data"] == {"host": "fab", "port": 80}
    assert diagnostics["online"] is True
    assert diagnostics["last_round"]["gcode_replies"]["M27"].startswith(
        "SD printing byte"
    )
    assert diagnostics["last_round"]["progress"] == pytest.approx(2.6)


async def test_diagnostics_describe_the_probe_ladder(
    hass: HomeAssistant, offline_entry: MockConfigEntry
) -> None:
    """A report says how long the integration is waiting and why."""
    coordinator = offline_entry.runtime_data
    await coordinator.async_refresh()
    await coordinator.async_refresh()

    diagnostics = await async_get_config_entry_diagnostics(hass, offline_entry)
    ladder = diagnostics["probe_ladder"]

    assert ladder["min_seconds"] == 15
    assert ladder["max_seconds"] == 1200
    assert ladder["current_seconds"] == 60
    assert ladder["silent_probes"] == 3
    assert diagnostics["online"] is False


async def test_diagnostics_report_the_firmware_identity(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """The M115 answer is in the report, including the UUID that identifies it."""
    diagnostics = await async_get_config_entry_diagnostics(hass, loaded_entry)

    assert diagnostics["identity"]["firmware"] == "Marlin 2.1.2.4 (Github)"
    assert diagnostics["identity"]["uuid"] == IDENTITY.uuid


async def test_diagnostics_of_a_machine_that_never_answered(
    hass: HomeAssistant, offline_entry: MockConfigEntry
) -> None:
    """A machine that was never awake still produces a useful report."""
    diagnostics = await async_get_config_entry_diagnostics(hass, offline_entry)

    assert diagnostics["identity"]["firmware"] is None
    assert (
        "refused the connection" in diagnostics["last_round"]["gcode_errors"]["probe"]
    )
    assert diagnostics["last_round"]["state"] == "offline"


async def test_the_button_is_the_only_one(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """No invented controls: this protocol describes reading, not driving."""
    registry = er.async_get(hass)
    buttons = [
        entry
        for entry in er.async_entries_for_config_entry(registry, loaded_entry.entry_id)
        if entry.entity_id.startswith("button.")
    ]

    assert [entry.unique_id for entry in buttons] == [f"{TEST_UNIQUE_ID}_probe_now"]
