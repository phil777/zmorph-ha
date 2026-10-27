"""Base class for Zmorph entities."""

from typing import override

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import ZMorphCoordinator


class ZMorphEntity(CoordinatorEntity[ZMorphCoordinator]):
    """One entity of one Zmorph machine.

    ``reads_the_machine`` says whether the entity shows a reading of the printer.
    Entities that describe the integration instead, like the next-probe time and
    the Probe now button, stay available while the machine is off: that is
    exactly when they matter.
    """

    _attr_has_entity_name = True

    reads_the_machine: bool = True

    def __init__(self, coordinator: ZMorphCoordinator) -> None:
        """Initialize the entity and attach it to the machine device."""
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.machine_id)},
            name=coordinator.config_entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=coordinator.identity.firmware,
            configuration_url=coordinator.client.base_url,
        )

    @property
    @override
    def available(self) -> bool:
        """Return whether this entity has something true to show."""
        if not super().available:
            return False
        if not self.reads_the_machine:
            return True
        return bool(self.coordinator.data and self.coordinator.data.online)
