"""Common fixtures for the Zmorph tests."""

from collections.abc import AsyncGenerator, Generator, Mapping
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zmorph.client import ZMorphClient
from custom_components.zmorph.const import (
    CONF_MAX_PROBE_INTERVAL,
    CONF_MIN_PROBE_INTERVAL,
    DEFAULT_MAX_PROBE_INTERVAL,
    DEFAULT_MIN_PROBE_INTERVAL,
    DOMAIN,
)

from .const import (
    BASE_URL,
    IDENTITY,
    ONLINE_STATUS,
    TEST_HOST,
    TEST_PORT,
    TEST_TITLE,
    TEST_UNIQUE_ID,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom integrations in every test of this suite."""


@pytest.fixture
def mock_client() -> Generator[AsyncMock]:
    """Return a client whose rounds are answered without a network.

    The class is replaced in both places that build one: the config flow, which
    checks the address, and the integration setup, which hands it to the
    coordinator.
    """
    client = AsyncMock(spec=ZMorphClient)
    client.host = TEST_HOST
    client.port = TEST_PORT
    client.base_url = BASE_URL
    client.machine_key = f"{TEST_HOST}:{TEST_PORT}"
    client.probe.return_value = ONLINE_STATUS
    client.fetch_identity.return_value = IDENTITY
    client.send.side_effect = lambda command: f"ok {command}\n"

    with (
        patch(
            "custom_components.zmorph.config_flow.ZMorphClient",
            return_value=client,
        ),
        patch("custom_components.zmorph.create_client", return_value=client),
    ):
        yield client


def make_entry(
    *,
    options: Mapping[str, Any] | None = None,
    unique_id: str | None = TEST_UNIQUE_ID,
    host: str = TEST_HOST,
    port: int = TEST_PORT,
) -> MockConfigEntry:
    """Return a config entry that is not added to Home Assistant yet."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=unique_id,
        title=TEST_TITLE,
        data={"host": host, "port": port},
        options={
            CONF_MIN_PROBE_INTERVAL: DEFAULT_MIN_PROBE_INTERVAL,
            CONF_MAX_PROBE_INTERVAL: DEFAULT_MAX_PROBE_INTERVAL,
            **(options or {}),
        },
        version=1,
        minor_version=1,
    )


@pytest.fixture
def config_entry(mock_client: AsyncMock) -> MockConfigEntry:
    """Return a config entry that is not set up yet."""
    return make_entry()


@pytest.fixture
async def loaded_entry(
    hass, config_entry: MockConfigEntry
) -> AsyncGenerator[MockConfigEntry]:
    """Return a config entry that finished setup with an answering machine."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    yield config_entry
    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture
async def offline_entry(
    hass, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> AsyncGenerator[MockConfigEntry]:
    """Return a set up entry for a machine that never answers.

    This is the state of a real Zmorph most of the day, so half of the suite runs
    against it.
    """
    from custom_components.zmorph.client import ZMorphOffline

    mock_client.probe.side_effect = ZMorphOffline(TEST_HOST, "refused the connection")
    mock_client.fetch_identity.side_effect = ZMorphOffline(TEST_HOST, "no answer")

    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    yield config_entry
    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


def state_of(hass: HomeAssistant, entity_id: str) -> State:
    """Return the state of an entity, failing the test when it was never created."""
    state = hass.states.get(entity_id)
    assert state is not None, f"{entity_id} was not created"
    return state


def registry_of(hass: HomeAssistant) -> er.EntityRegistry:
    """Return the entity registry."""
    return er.async_get(hass)


def registry_entry_of(hass: HomeAssistant, entity_id: str) -> RegistryEntry:
    """Return the registry entry of an entity, failing when it is not registered."""
    entry = er.async_get(hass).async_get(entity_id)
    assert entry is not None, f"{entity_id} is not in the entity registry"
    return entry
