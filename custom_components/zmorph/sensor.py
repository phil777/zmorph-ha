"""Support for Zmorph sensors."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfLength,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import ZMorphConfigEntry, ZMorphCoordinator
from .entity import ZMorphEntity
from .models import ZMorphState, ZMorphStatus

PARALLEL_UPDATES = 0

# A sensor value is a number, a string, or a timestamp for the probe schedule.
type SensorValue = StateType | date | datetime | Decimal


@dataclass(frozen=True, kw_only=True)
class ZMorphSensorEntityDescription(SensorEntityDescription):
    """Describe one Zmorph sensor."""

    # Reading of the machine, or of the integration itself.
    value_fn: Callable[[ZMorphStatus], SensorValue] = lambda _: None
    probe_value_fn: Callable[[ZMorphCoordinator], SensorValue] | None = None
    reads_the_machine: bool = True


def _progress(status: ZMorphStatus) -> float | None:
    """Return the byte-derived percentage, or None when nothing is printing."""
    return status.progress


SENSORS: tuple[ZMorphSensorEntityDescription, ...] = (
    ZMorphSensorEntityDescription(
        key="state",
        translation_key="state",
        device_class=SensorDeviceClass.ENUM,
        options=[state.value for state in ZMorphState],
        value_fn=lambda status: status.state.value,
        # Deliberately not gated on the machine answering: a printer that is off
        # has a state worth showing, and a grey "unavailable" says less than
        # "Offline". The measurement entities below do go unavailable.
        reads_the_machine=False,
    ),
    ZMorphSensorEntityDescription(
        key="progress",
        translation_key="progress",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_progress,
    ),
    ZMorphSensorEntityDescription(
        key="nozzle_temperature",
        translation_key="nozzle_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda status: status.temperatures.nozzle,
    ),
    ZMorphSensorEntityDescription(
        key="nozzle_target",
        translation_key="nozzle_target",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda status: status.temperatures.nozzle_target,
    ),
    ZMorphSensorEntityDescription(
        key="bed_temperature",
        translation_key="bed_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda status: status.temperatures.bed,
    ),
    ZMorphSensorEntityDescription(
        key="bed_target",
        translation_key="bed_target",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda status: status.temperatures.bed_target,
    ),
    ZMorphSensorEntityDescription(
        key="position_x",
        translation_key="position_x",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda status: status.position.x if status.position else None,
    ),
    ZMorphSensorEntityDescription(
        key="position_y",
        translation_key="position_y",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda status: status.position.y if status.position else None,
    ),
    ZMorphSensorEntityDescription(
        key="position_z",
        translation_key="position_z",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda status: status.position.z if status.position else None,
    ),
    ZMorphSensorEntityDescription(
        key="bytes_printed",
        translation_key="bytes_printed",
        native_unit_of_measurement="B",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda status: status.print_status.bytes_printed,
    ),
    ZMorphSensorEntityDescription(
        key="bytes_total",
        translation_key="bytes_total",
        native_unit_of_measurement="B",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda status: status.print_status.bytes_total,
    ),
    # The probe ladder: entities of the integration, not of the machine, so they
    # stay readable while the printer is off.
    ZMorphSensorEntityDescription(
        key="next_probe",
        translation_key="next_probe",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        reads_the_machine=False,
        probe_value_fn=lambda coordinator: coordinator.next_probe,
    ),
    ZMorphSensorEntityDescription(
        key="probe_interval",
        translation_key="probe_interval",
        native_unit_of_measurement="s",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        reads_the_machine=False,
        probe_value_fn=lambda coordinator: int(
            coordinator.probe_interval.total_seconds()
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZMorphConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Zmorph sensors of one config entry."""
    coordinator = entry.runtime_data

    async_add_entities(
        ZMorphSensorEntity(coordinator, description) for description in SENSORS
    )


class ZMorphSensorEntity(ZMorphEntity, SensorEntity):
    """One value of the machine, or of the probe ladder."""

    entity_description: ZMorphSensorEntityDescription

    def __init__(
        self,
        coordinator: ZMorphCoordinator,
        description: ZMorphSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self.reads_the_machine = description.reads_the_machine
        self._attr_unique_id = f"{coordinator.machine_id}_{description.key}"

    @property
    @override
    def native_value(self) -> SensorValue:
        """Return the value of this sensor."""
        description = self.entity_description
        if (probe_fn := description.probe_value_fn) is not None:
            return probe_fn(self.coordinator)
        if self.coordinator.data is None:
            return None
        return description.value_fn(self.coordinator.data)

    @property
    @override
    def extra_state_attributes(self) -> dict[str, object] | None:
        """Return the silent-probe count next to the ladder entities."""
        if self.entity_description.key != "next_probe":
            return None
        return {"silent_probes": self.coordinator.silent_probes}

    @override
    @property
    def should_poll(self) -> bool:
        """Never poll: the coordinator pushes."""
        return False
