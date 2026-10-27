"""Tests for the Zmorph config flow."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    ConfigEntryState,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zmorph.client import ZMorphOffline, ZMorphProtocolError
from custom_components.zmorph.const import (
    CONF_MAX_PROBE_INTERVAL,
    CONF_MIN_PROBE_INTERVAL,
    DEFAULT_MAX_PROBE_INTERVAL,
    DEFAULT_MIN_PROBE_INTERVAL,
    DOMAIN,
)
from custom_components.zmorph.models import ZMorphIdentity

from .conftest import make_entry
from .const import (
    IDENTITY,
    TEST_HOST,
    TEST_PORT,
    TEST_TITLE,
    TEST_UNIQUE_ID,
    TEST_UUID_UNIQUE_ID,
    USER_INPUT,
)

NO_UUID = ZMorphIdentity(firmware="Marlin 1.0")


async def test_the_form_asks_for_the_address(hass) -> None:
    """The machine is found by its name on the network, which defaults to fab."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}

    keys = [str(item) for item in result["data_schema"].schema]
    assert keys == [CONF_HOST, CONF_PORT]


async def test_an_answering_machine_creates_one_entry(
    hass, mock_client: AsyncMock
) -> None:
    """A reachable machine is set up, identified by the UUID its firmware reports."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == TEST_TITLE
    assert result["data"] == {CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT}
    # A UUID survives a new name and a new address, so it beats the address.
    assert result["result"].unique_id == TEST_UUID_UNIQUE_ID
    # The probe ladder starts at its defaults, ready to be changed in the options.
    assert result["result"].options == {
        CONF_MIN_PROBE_INTERVAL: DEFAULT_MIN_PROBE_INTERVAL,
        CONF_MAX_PROBE_INTERVAL: DEFAULT_MAX_PROBE_INTERVAL,
    }


async def test_a_machine_that_is_off_still_gets_added(
    hass, mock_client: AsyncMock
) -> None:
    """The printer is off most of the day, so being off must not block setup."""
    mock_client.probe.side_effect = ZMorphOffline(TEST_HOST, "refused the connection")
    mock_client.fetch_identity.return_value = NO_UUID
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    # With nothing to identify it by, the address becomes the id.
    assert result["result"].unique_id == TEST_UNIQUE_ID


@pytest.mark.parametrize("identity", [IDENTITY, NO_UUID])
async def test_the_same_machine_is_not_added_twice(
    hass, mock_client: AsyncMock, identity: ZMorphIdentity
) -> None:
    """One machine, one entry, whether it reports a UUID or only an address."""
    entry = make_entry(
        unique_id=TEST_UUID_UNIQUE_ID if identity.machine_id else TEST_UNIQUE_ID
    )
    entry.add_to_hass(hass)
    mock_client.fetch_identity.return_value = identity

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    # The user types the same address in another spelling.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "FAB", CONF_PORT: TEST_PORT}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_another_host_is_refused(hass, mock_client: AsyncMock) -> None:
    """A host that answers with something else is not the machine."""
    mock_client.probe.side_effect = ZMorphProtocolError(TEST_HOST, "'<html>'")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "not_a_zmorph"}

    # The user fixes the address and it works.
    mock_client.probe.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "fab2", CONF_PORT: TEST_PORT}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == TEST_UUID_UNIQUE_ID


async def test_reconfigure_moves_an_address_identified_entry(
    hass, mock_client: AsyncMock
) -> None:
    """A machine that got a new name keeps its entry, and the id follows."""
    entry = make_entry()  # identified by its address
    entry.add_to_hass(hass)
    mock_client.fetch_identity.return_value = NO_UUID

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "fab-new", CONF_PORT: 8080}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == "fab-new"
    assert entry.data[CONF_PORT] == 8080
    assert entry.unique_id == "zmorph:host:fab-new:8080"


async def test_reconfigure_keeps_the_uuid_of_the_same_machine(
    hass, mock_client: AsyncMock
) -> None:
    """A new address for a machine known by UUID does not change what it is."""
    entry = make_entry(unique_id=TEST_UUID_UNIQUE_ID)
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "zmorph2.local", CONF_PORT: TEST_PORT}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == "zmorph2.local"
    assert entry.unique_id == TEST_UUID_UNIQUE_ID


async def test_reconfigure_refuses_a_different_machine(
    hass, mock_client: AsyncMock
) -> None:
    """Another printer at the new address is not the machine of this entry."""
    entry = make_entry(unique_id=TEST_UUID_UNIQUE_ID)
    entry.add_to_hass(hass)
    mock_client.fetch_identity.return_value = ZMorphIdentity(
        firmware="Marlin 2.1.2.4", uuid="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "other-printer", CONF_PORT: TEST_PORT}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"
    assert entry.data[CONF_HOST] == TEST_HOST
    assert entry.unique_id == TEST_UUID_UNIQUE_ID


async def test_reconfigure_adopts_a_uuid_the_machine_reveals(
    hass, mock_client: AsyncMock
) -> None:
    """An entry added while the machine was off is upgraded once it answers."""
    entry = make_entry()  # address identified
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.unique_id == TEST_UUID_UNIQUE_ID


async def test_reconfigure_reports_a_host_that_is_not_the_machine(
    hass, loaded_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Reconfiguring onto something else is refused, and says why."""
    mock_client.probe.side_effect = ZMorphProtocolError("printer-print", "'<html>'")
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": loaded_entry.entry_id},
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "printer-print", CONF_PORT: TEST_PORT}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "not_a_zmorph"}
    assert loaded_entry.data[CONF_HOST] == TEST_HOST


async def test_the_probe_ladder_is_configurable(
    hass, loaded_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The starting wait and the ceiling are options, and reload the entry."""
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    keys = [str(item) for item in result["data_schema"].schema]
    assert keys == [CONF_MIN_PROBE_INTERVAL, CONF_MAX_PROBE_INTERVAL]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MIN_PROBE_INTERVAL: 30, CONF_MAX_PROBE_INTERVAL: 900}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_MIN_PROBE_INTERVAL: 30,
        CONF_MAX_PROBE_INTERVAL: 900,
    }
    assert loaded_entry.options[CONF_MIN_PROBE_INTERVAL] == 30
    # OptionsFlowWithReload: the entry came back up on its own.
    assert loaded_entry.state is ConfigEntryState.LOADED


async def test_the_new_limits_take_effect_after_the_reload(
    hass, loaded_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Changing the ladder is not cosmetic: the coordinator uses the new values."""
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)

    await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MIN_PROBE_INTERVAL: 120, CONF_MAX_PROBE_INTERVAL: 3600}
    )
    await hass.async_block_till_done()

    assert loaded_entry.state is ConfigEntryState.LOADED
    assert loaded_entry.runtime_data.min_interval == timedelta(seconds=120)
    assert loaded_entry.runtime_data.max_interval == timedelta(seconds=3600)


async def test_the_ceiling_cannot_be_below_the_start(
    hass, loaded_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A ladder that ends before it starts is refused in the dialog."""
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MIN_PROBE_INTERVAL: 600, CONF_MAX_PROBE_INTERVAL: 60}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_MAX_PROBE_INTERVAL: "max_below_min"}

    # Corrected, it goes through.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MIN_PROBE_INTERVAL: 60, CONF_MAX_PROBE_INTERVAL: 600}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
