"""Diagnostics support for the Zmorph integration."""

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    CONF_MAX_PROBE_INTERVAL,
    CONF_MIN_PROBE_INTERVAL,
    DEFAULT_MAX_PROBE_INTERVAL,
    DEFAULT_MIN_PROBE_INTERVAL,
)
from .coordinator import ZMorphConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ZMorphConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    Home Assistant offers this in the three-dot menu of the entry. The useful part
    of it is ``last_round``, the raw text of every G-code answer: that is what
    tells whether a machine answers differently from what the parsers expect.
    """
    coordinator = entry.runtime_data
    status = coordinator.data

    return {
        # Home Assistant links the report to the entry through these two keys.
        "config_entry_id": entry.entry_id,
        "config_entry_data": dict(entry.data),
        "config_entry_options": dict(entry.options),
        "config_entry": {
            "version": f"{entry.version}.{entry.minor_version}",
            "source": entry.source,
            "state": entry.state.value,
            "pref_disable_polling": entry.pref_disable_polling,
            "title": entry.title,
        },
        "probe_ladder": {
            "min_seconds": int(coordinator.min_interval.total_seconds()),
            "max_seconds": int(coordinator.max_interval.total_seconds()),
            "current_seconds": int(coordinator.probe_interval.total_seconds()),
            "silent_probes": coordinator.silent_probes,
            "next_probe": (
                coordinator.next_probe.isoformat() if coordinator.next_probe else None
            ),
            "defaults": {
                CONF_MIN_PROBE_INTERVAL: DEFAULT_MIN_PROBE_INTERVAL,
                CONF_MAX_PROBE_INTERVAL: DEFAULT_MAX_PROBE_INTERVAL,
            },
        },
        "identity": asdict(coordinator.identity),
        "online": coordinator.awake,
        "last_round": status.as_dict() if status else None,
        "last_exception": str(coordinator.last_exception)
        if coordinator.last_exception
        else None,
    }
