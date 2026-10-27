"""Tests for the G-code parsers."""

import pytest

from custom_components.zmorph.models import (
    ZMorphPrintStatus,
    ZMorphState,
    offline_status,
    parse_m27,
    parse_m105,
    parse_m114,
    parse_m115,
)

from .const import (
    EXPECTED_PROGRESS,
    IDENTITY,
    M27_IDLE,
    M27_PRINTING,
    M105_REPLY,
    M114_REPLY,
    M115_REPLY,
    ONLINE_STATUS,
    TEMPERATURES,
)


def test_m27_while_printing() -> None:
    """The byte position of the protocol notes parses into a printing status."""
    status = parse_m27(M27_PRINTING)

    assert status.state is ZMorphState.PRINTING
    assert status.bytes_printed == 24758
    assert status.bytes_total == 968376
    assert status.printing


def test_m27_progress_comes_from_the_bytes() -> None:
    """Progress is the printed share of the file, not a firmware percentage."""
    assert parse_m27(M27_PRINTING).progress == pytest.approx(EXPECTED_PROGRESS)
    assert parse_m27("SD printing byte 968376/968376").progress == 100.0
    assert parse_m27("SD printing byte 484188/968376").progress == 50.0


def test_m27_progress_is_capped() -> None:
    """A firmware that reports past the end of the file does not pass 100."""
    assert parse_m27("SD printing byte 10/4").progress == 100.0


def test_m27_when_idle() -> None:
    """The idle answer carries no bytes, so there is no progress."""
    status = parse_m27(M27_IDLE)

    assert status.state is ZMorphState.IDLE
    assert status.bytes_printed is None
    assert status.progress is None
    assert not status.printing


@pytest.mark.parametrize(
    "reply", ["ok\n", "", "Unknown command", "echo:Hidden M27 received"]
)
def test_m27_says_unknown_rather_than_guessing(reply: str) -> None:
    """An answer that is neither printing nor idle is reported as unknown."""
    assert parse_m27(reply).state is ZMorphState.UNKNOWN


def test_m105_reads_extruder_and_bed() -> None:
    """T is the extruder and B the bed, current and target."""
    temperatures = parse_m105(M105_REPLY)

    assert temperatures.nozzle == pytest.approx(189.9)
    assert temperatures.nozzle_target == pytest.approx(190.0)
    assert temperatures.bed == pytest.approx(60.0)
    assert temperatures.bed_target == pytest.approx(60.0)
    assert temperatures.has_readings


def test_m105_keeps_unknown_heaters_uninterpreted() -> None:
    """Q and P have no documented meaning, so they are kept raw, not renamed."""
    temperatures = parse_m105(M105_REPLY)

    assert set(temperatures.other) == {"Q", "P"}
    # Q reports inf, which is not a temperature.
    assert temperatures.other["Q"] == (None, 0.0)
    assert temperatures.other["P"][0] == pytest.approx(45.7)


def test_m105_rejects_infinite_values_as_no_reading() -> None:
    """inf and nan never reach an entity."""
    assert parse_m105("ok T:inf /0.0 @0").nozzle is None
    assert parse_m105("ok T:nan /nan @0").nozzle_target is None
    assert not parse_m105("ok ").has_readings


def test_m114_reads_the_coordinates() -> None:
    """M114 gives the position in millimetres."""
    position = parse_m114(M114_REPLY)

    assert position.x == pytest.approx(101.0120)
    assert position.y == pytest.approx(152.5530)
    assert position.z == pytest.approx(0.2000)
    assert position.e == pytest.approx(21.3844)


def test_m114_with_a_partial_answer() -> None:
    """A missing axis stays unknown instead of becoming zero."""
    position = parse_m114("ok C: X:12.5 Z:0.3")

    assert position.x == pytest.approx(12.5)
    assert position.y is None
    assert position.z == pytest.approx(0.3)


def test_m115_gives_firmware_and_uuid() -> None:
    """The identity answer carries the only stable id the machine offers."""
    identity = parse_m115(M115_REPLY)

    assert identity == IDENTITY
    assert identity.machine_id == "32333351353251002A20205019002F53"


def test_m115_without_a_uuid() -> None:
    """A firmware that reports no UUID leaves the id to the address."""
    identity = parse_m115("FIRMWARE_NAME:Marlin 1.0 MACHINE_TYPE:Fab\nok")

    assert identity.firmware == "Marlin 1.0"
    assert identity.machine_id is None


def test_offline_status_keeps_the_last_readings() -> None:
    """A machine that is off does not invent new numbers, and keeps the old ones."""
    status = offline_status(ONLINE_STATUS, "fab refused the connection")

    assert status.online is False
    assert status.state is ZMorphState.OFFLINE
    assert status.progress is None
    assert status.temperatures == TEMPERATURES
    assert status.print_status == ONLINE_STATUS.print_status
    assert status.errors["probe"] == "fab refused the connection"


def test_offline_status_without_any_previous_round() -> None:
    """The first probe of a cold start has nothing to carry over."""
    status = offline_status(None, "no answer yet")

    assert status.online is False
    assert not status.temperatures.has_readings
    assert status.position is None


def test_print_status_defaults_to_idle_shape() -> None:
    """A status built without bytes has no progress, whatever the state."""
    assert ZMorphPrintStatus(state=ZMorphState.PRINTING).progress is None
