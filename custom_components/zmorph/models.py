"""Parsers for the plain-text answers of the Zmorph Fab.

The machine speaks G-code, not JSON; see docs/zmorph_fab_protocol.txt. Each
command answers with text whose shape the firmware fixes:

    M27   SD printing byte 24758/968376    while printing
          Not currently playing            when idle
    M105  ok T:189.9 /190.0 @111 Q:inf /0.0 @0 P:45.7 /0.0 @0 B:60.0 /60.0 @255
    M114  ok C: X:101.0120 Y:152.5530 Z:0.2000 E:21.3844
    M115  FIRMWARE_NAME:Marlin 2.1.2.4 (Github) SOURCE_CODE_URL:... UUID:...

Every parser is forgiving on purpose: an answer it cannot read yields no value
instead of raising, so one unreadable line never hides the readings that did
arrive.
"""

import math
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# "SD printing byte <printed>/<total>"
_PRINT_RE = re.compile(r"SD printing byte\s+(\d+)\s*/\s*(\d+)", re.IGNORECASE)

# Answers that mean: awake, but no job running.
_IDLE_MARKERS = ("not currently playing", "no card", "card detached", "not sd printing")

# "T:189.9 /190.0" or "B:60.0 /60.0". The firmware reports inf and nan here.
_HEATER_RE = re.compile(
    r"\b(?P<key>[A-Z])\s*:\s*(?P<current>-?\d+(?:\.\d+)?|inf|nan)"
    r"\s*/\s*(?P<target>-?\d+(?:\.\d+)?|inf|nan)",
    re.IGNORECASE,
)

# "X:101.0120" in the M114 answer.
_AXIS_RE = re.compile(r"\b(?P<axis>[XYZE])\s*:\s*(?P<value>-?\d+(?:\.\d+)?)")

# The M115 answer is a run of KEY:VALUE pairs separated by spaces, so the
# firmware name runs until the next key: "FIRMWARE_NAME:Marlin 2.1.2.4 (Github)
# SOURCE_CODE_URL:...". Some builds also carry a UUID, the only stable identity
# the machine offers.
_FIRMWARE_RE = re.compile(
    r"FIRMWARE_NAME\s*:\s*(?P<value>.*?)(?=\s+[A-Z_][A-Z0-9_]*\s*:|$)",
    re.IGNORECASE | re.MULTILINE,
)
_UUID_RE = re.compile(r"\bUUID\s*:\s*([0-9A-Fa-fx-]{4,})", re.IGNORECASE)


class ZMorphState(StrEnum):
    """What the machine is doing.

    ``OFFLINE`` is not a firmware answer. It is what the integration reports when
    the last probe reached nothing, which is the state of this machine most of
    the day.
    """

    IDLE = "idle"
    PRINTING = "printing"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


def _number(text: str) -> float | None:
    """Return the number in text, or None for inf, nan and junk."""
    try:
        value = float(text)
    except ValueError:
        return None
    if math.isinf(value) or math.isnan(value):
        return None
    return value


@dataclass(frozen=True, kw_only=True)
class ZMorphIdentity:
    """What M115 says about the machine, when it answers at all."""

    firmware: str | None = None
    uuid: str | None = None
    raw: str = ""

    @property
    def machine_id(self) -> str | None:
        """Return the identifier the firmware offers, if it offers one."""
        return self.uuid or None


def parse_m115(reply: str) -> ZMorphIdentity:
    """Parse the answer of M115.

    Marlin builds answer with at least ``FIRMWARE_NAME:``, and some also carry a
    ``UUID:``. That UUID is the only stable identity the machine offers, so it is
    what the integration prefers for its unique id.
    """
    firmware = _FIRMWARE_RE.search(reply)
    unique = _UUID_RE.search(reply)
    return ZMorphIdentity(
        firmware=firmware.group("value").strip() if firmware else None,
        uuid=unique.group(1).strip() if unique else None,
        raw=reply.strip(),
    )


@dataclass(frozen=True, kw_only=True)
class ZMorphPrintStatus:
    """The answer of M27: how far the machine is into the file."""

    state: ZMorphState
    bytes_printed: int | None = None
    bytes_total: int | None = None

    @property
    def progress(self) -> float | None:
        """Return the percentage of the file printed, or None when idle.

        The firmware reports neither a percentage nor a time estimate, so
        progress is deduced from the byte position in the file. With no job
        running there are no bytes to divide, and the state entity says idle.
        """
        if (
            self.state is not ZMorphState.PRINTING
            or self.bytes_printed is None
            or not self.bytes_total
        ):
            return None
        return round(min(self.bytes_printed / self.bytes_total * 100, 100.0), 1)

    @property
    def printing(self) -> bool:
        """Return whether the machine is running a job."""
        return self.state is ZMorphState.PRINTING


def parse_m27(reply: str) -> ZMorphPrintStatus:
    """Parse the answer of M27."""
    text = reply.strip()

    if match := _PRINT_RE.search(text):
        return ZMorphPrintStatus(
            state=ZMorphState.PRINTING,
            bytes_printed=int(match.group(1)),
            bytes_total=int(match.group(2)),
        )

    if any(marker in text.lower() for marker in _IDLE_MARKERS):
        return ZMorphPrintStatus(state=ZMorphState.IDLE)

    return ZMorphPrintStatus(state=ZMorphState.UNKNOWN)


@dataclass(frozen=True, kw_only=True)
class ZMorphTemperatures:
    """The answer of M105.

    ``T`` is the extruder and ``B`` the bed. The machine also reports ``Q`` and
    ``P``, whose meaning is not documented: they are kept uninterpreted in
    ``other`` instead of guessed at, and they show up in diagnostics.
    """

    nozzle: float | None = None
    nozzle_target: float | None = None
    bed: float | None = None
    bed_target: float | None = None
    other: dict[str, tuple[float | None, float | None]] = field(default_factory=dict)

    @property
    def has_readings(self) -> bool:
        """Return whether any temperature came through."""
        return any(
            value is not None
            for value in (self.nozzle, self.nozzle_target, self.bed, self.bed_target)
        )


def parse_m105(reply: str) -> ZMorphTemperatures:
    """Parse the answer of M105."""
    nozzle = nozzle_target = bed = bed_target = None
    other: dict[str, tuple[float | None, float | None]] = {}

    for match in _HEATER_RE.finditer(reply):
        key = match.group("key").upper()
        current = _number(match.group("current"))
        target = _number(match.group("target"))

        if key == "T":
            nozzle, nozzle_target = current, target
        elif key == "B":
            bed, bed_target = current, target
        elif key not in other:
            other[key] = (current, target)

    return ZMorphTemperatures(
        nozzle=nozzle,
        nozzle_target=nozzle_target,
        bed=bed,
        bed_target=bed_target,
        other=other,
    )


@dataclass(frozen=True, kw_only=True)
class ZMorphPosition:
    """The answer of M114: the coordinates in millimetres."""

    x: float | None = None
    y: float | None = None
    z: float | None = None
    e: float | None = None


def parse_m114(reply: str) -> ZMorphPosition:
    """Parse the answer of M114."""
    values: dict[str, float | None] = {}
    for match in _AXIS_RE.finditer(reply):
        axis = match.group("axis").upper()
        if axis not in values:
            values[axis] = _number(match.group("value"))

    return ZMorphPosition(
        x=values.get("X"), y=values.get("Y"), z=values.get("Z"), e=values.get("E")
    )


@dataclass(frozen=True, kw_only=True)
class ZMorphStatus:
    """One probe round: the commands that were sent and the answers received.

    ``online`` is False when the round reached nothing. The readings then keep the
    values of the last round that did arrive, so a machine switched off between
    probes does not lose its last temperatures; only the state says offline.
    """

    online: bool
    print_status: ZMorphPrintStatus
    temperatures: ZMorphTemperatures
    position: ZMorphPosition | None = None
    replies: dict[str, str] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def state(self) -> ZMorphState:
        """Return what the machine is doing."""
        if not self.online:
            return ZMorphState.OFFLINE
        return self.print_status.state

    @property
    def progress(self) -> float | None:
        """Return the byte-based percentage, or None when there is no job."""
        if not self.online:
            return None
        return self.print_status.progress

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly view for diagnostics."""
        return {
            "online": self.online,
            "state": self.state.value,
            "bytes_printed": self.print_status.bytes_printed,
            "bytes_total": self.print_status.bytes_total,
            "progress": self.progress,
            "temperatures": {
                "nozzle": self.temperatures.nozzle,
                "nozzle_target": self.temperatures.nozzle_target,
                "bed": self.temperatures.bed,
                "bed_target": self.temperatures.bed_target,
                "other": {
                    key: {"current": current, "target": target}
                    for key, (current, target) in self.temperatures.other.items()
                },
            },
            "position": {
                "x": self.position.x if self.position else None,
                "y": self.position.y if self.position else None,
                "z": self.position.z if self.position else None,
                "e": self.position.e if self.position else None,
            },
            "gcode_replies": {
                command: reply.strip() for command, reply in self.replies.items()
            },
            "gcode_errors": self.errors,
        }


def offline_status(previous: ZMorphStatus | None, reason: str) -> ZMorphStatus:
    """Return an offline snapshot, carrying over the readings it can.

    The state of the machine is reported as offline while the last temperatures
    and position stay visible as historical values: they were true a moment ago,
    and a printer that is off does not change them.
    """
    return ZMorphStatus(
        online=False,
        print_status=(
            previous.print_status
            if previous
            else ZMorphPrintStatus(state=ZMorphState.OFFLINE)
        ),
        temperatures=(previous.temperatures if previous else ZMorphTemperatures()),
        position=previous.position if previous else None,
        replies=dict(previous.replies) if previous else {},
        errors={"probe": reason},
    )
