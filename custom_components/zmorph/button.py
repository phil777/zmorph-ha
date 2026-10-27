"""Support for the Zmorph probe button."""

from typing import override

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ZMorphConfigEntry, ZMorphCoordinator
from .entity import ZMorphEntity

PARALLEL_UPDATES = 0

# One button only: force a probe now instead of waiting for the ladder. The
# machine has no documented controls worth a button, so nothing else lives here.
BUTTONS: tuple[ButtonEntityDescription, ...] = (
    ButtonEntityDescription(
        key="probe_now",
        translation_key="probe_now",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZMorphConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Zmorph button of one config entry."""
    coordinator = entry.runtime_data

    async_add_entities(
        ZMorphProbeButton(coordinator, description) for description in BUTTONS
    )


class ZMorphProbeButton(ZMorphEntity, ButtonEntity):
    """Probe the machine right away, whatever the ladder is waiting for."""

    entity_description: ButtonEntityDescription

    # The button belongs to the integration, not to a reading of the machine, so
    # it stays usable while the printer is off: that is when it is needed.
    reads_the_machine = False

    def __init__(
        self,
        coordinator: ZMorphCoordinator,
        description: ButtonEntityDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.machine_id}_{description.key}"

    @override
    async def async_press(self) -> None:
        """Probe the machine now and restart the ladder at the minimum."""
        await self.coordinator.async_probe_now()
