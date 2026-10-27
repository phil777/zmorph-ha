"""The Zmorph integration."""

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from .client import create_client
from .const import DEFAULT_PORT, PLATFORMS
from .coordinator import ZMorphConfigEntry, ZMorphCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ZMorphConfigEntry) -> bool:
    """Set up Zmorph from a config entry."""
    client = create_client(
        hass,
        host=entry.data[CONF_HOST],
        port=int(entry.data.get(CONF_PORT, DEFAULT_PORT)),
    )

    # The probe limits come from the options. A ladder the wrong way round cannot
    # work, so it raises ConfigEntryError and Home Assistant shows the reason on
    # the entry instead of pretending the machine is unreachable.
    coordinator = ZMorphCoordinator(hass, entry, client)

    # A machine that does not answer is not a setup failure. The first round
    # reports offline, the ladder grows, and the Probe now button stays there for
    # whoever switches the printer on. Only a wrong address is an error.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ZMorphConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
