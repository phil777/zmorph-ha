"""Transport for the Zmorph Fab web service.

The machine exposes one endpoint and speaks plain G-code::

    POST http://fab/command     body: "M27\\n"     reply: plain text

The trailing line feed belongs to the protocol: without it the firmware waits for
the rest of the command. There is no authentication and no JSON. See
docs/zmorph_fab_protocol.txt.

A machine that is switched off is the normal case, not an exceptional one, so an
unreachable machine raises :class:`ZMorphOffline` and the coordinator turns that
into a longer wait before the next probe.
"""

from __future__ import annotations

from typing import Self

import aiohttp
from homeassistant.const import __version__ as ha_version
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import COMMAND_PATH, DEFAULT_PORT, DOMAIN, LOGGER, REQUEST_TIMEOUT
from .models import (
    ZMorphIdentity,
    ZMorphPosition,
    ZMorphPrintStatus,
    ZMorphState,
    ZMorphStatus,
    ZMorphTemperatures,
    parse_m27,
    parse_m105,
    parse_m114,
    parse_m115,
)

M27 = "M27"  # byte position in the file being printed, or "Not currently playing"
M105 = "M105"  # temperatures: T is the extruder, B the bed
M114 = "M114"  # coordinates
M115 = "M115"  # firmware name and, on some builds, a UUID

# One round of probing. M27 leads: it is where progress comes from.
PROBE_COMMANDS: tuple[str, ...] = (M27, M105, M114)

# Text only a RepRap-style controller answers with. It tells a machine that is
# switched off apart from a host that answers with something else entirely.
_FIRMWARE_MARKERS = ("ok", "t:", "sd printing byte", "not currently playing", "error:")
_HTML_MARKERS = ("<!doctype", "<html", "<?xml")


class ZMorphError(HomeAssistantError):
    """Base error for the Zmorph transport."""


class ZMorphOffline(ZMorphError):
    """The machine did not answer: switched off, asleep, or unplugged."""

    def __init__(self, host: str, reason: str = "did not answer") -> None:
        """Initialize the error."""
        super().__init__(
            f"{host} {reason}",
            translation_domain=DOMAIN,
            translation_key="offline",
            translation_placeholders={"host": host},
        )


class ZMorphProtocolError(ZMorphError):
    """Something answered, but it is not a Zmorph controller."""

    def __init__(self, host: str, detail: str) -> None:
        """Initialize the error."""
        super().__init__(
            f"{host} answered {detail}, which is not G-code output",
            translation_domain=DOMAIN,
            translation_key="not_a_zmorph",
            translation_placeholders={"host": host},
        )


UUID_PREFIX: str = f"{DOMAIN}:uuid:"
HOST_PREFIX: str = f"{DOMAIN}:host:"


def machine_unique_id(host: str, port: int = DEFAULT_PORT) -> str:
    """Return the id of a machine from its address.

    The Zmorph reports no serial number over this endpoint, so the address the
    user typed is the handle. It is the fallback, used when the machine was off
    while it was added, and it is marked as such so a later UUID can replace it.
    """
    name = host.lower().rstrip(".")
    return f"{HOST_PREFIX}{name}:{port}" if port != 80 else f"{HOST_PREFIX}{name}"


def resolve_unique_id(
    identity: ZMorphIdentity | None, host: str, port: int = DEFAULT_PORT
) -> str:
    """Return the best id a machine can offer, and its address as the fallback.

    A firmware that answers M115 with a UUID is preferred: it survives a new name,
    a new address, and a replaced board.
    """
    if identity is not None and (machine_id := identity.machine_id):
        return f"{UUID_PREFIX}{machine_id.lower()}"
    return machine_unique_id(host, port)


def identified_by_uuid(unique_id: str) -> bool:
    """Return whether an entry is identified by a firmware UUID."""
    return unique_id.startswith(UUID_PREFIX)


def create_client(
    hass: HomeAssistant,
    *,
    host: str,
    port: int = DEFAULT_PORT,
) -> ZMorphClient:
    """Return a client bound to the shared Home Assistant web session."""
    return ZMorphClient(async_get_clientsession(hass), host=host, port=port)


class ZMorphClient:
    """Send G-code to one Zmorph Fab and read the plain-text answers."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        host: str,
        port: int = DEFAULT_PORT,
    ) -> None:
        """Initialize the client for one address."""
        self._session = session
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.machine_key = f"{host.lower()}:{port}"

    @classmethod
    def from_entry(
        cls, hass: HomeAssistant, *, host: str, port: int = DEFAULT_PORT
    ) -> Self:
        """Return a client using the shared web session of this Home Assistant."""
        return cls(async_get_clientsession(hass), host=host, port=port)

    async def send(self, command: str) -> str:
        """Send one G-code and return its answer.

        Raises:
            ZMorphOffline: nothing answered, or an error status. This is the
                usual state of a machine that is switched off.
            ZMorphProtocolError: something answered, but it is not a controller.
        """
        url = f"{self.base_url}{COMMAND_PATH}"
        LOGGER.debug("G-code -> %s: %s", url, command)

        try:
            async with self._session.post(
                url,
                # The line feed terminates the command for the firmware.
                data=f"{command}\n",
                headers={
                    "Content-Type": "text/plain",
                    "User-Agent": f"HomeAssistant/{ha_version}",
                },
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                if response.status == 404:
                    # A host serving something else will never serve this
                    # endpoint, so this is not a machine problem.
                    raise ZMorphProtocolError(self.host, f"HTTP 404 on {COMMAND_PATH}")
                if response.status >= 400:
                    raise ZMorphOffline(self.host, f"answered HTTP {response.status}")
                text = await response.text()
        except aiohttp.ClientError as err:
            raise ZMorphOffline(self.host, _reason(err)) from err
        except TimeoutError as err:
            raise ZMorphOffline(self.host, "timed out") from err

        answer = text.strip()
        LOGGER.debug("G-code <- %s: %s", command, answer)

        if not _looks_like_firmware(answer):
            raise ZMorphProtocolError(self.host, repr(answer[:80]))

        return text

    async def probe(self) -> ZMorphStatus:
        """Send every command of one round and collect the answers.

        The first command decides whether the machine is awake. When it answers
        and a later command fails, the round still counts: what arrived is used,
        and what did not is recorded in ``errors``.
        """
        replies: dict[str, str] = {}
        errors: dict[str, str] = {}

        for index, command in enumerate(PROBE_COMMANDS):
            try:
                replies[command] = await self.send(command)
            except ZMorphOffline:
                if index == 0:
                    raise
                errors[command] = "the machine stopped answering"
                break
            except ZMorphProtocolError as err:
                if index == 0:
                    raise
                errors[command] = str(err)

        return build_status(replies, errors, host=self.host)

    async def fetch_identity(self) -> ZMorphIdentity:
        """Read the firmware answer of M115.

        An off machine gives no identity, which is not an error here: the caller
        gets an empty :class:`ZMorphIdentity`.
        """
        try:
            reply = await self.send(M115)
        except (ZMorphOffline, ZMorphProtocolError) as err:
            LOGGER.debug("%s gave no identity: %s", self.host, err)
            return ZMorphIdentity()

        identity = parse_m115(reply)
        return ZMorphIdentity(
            firmware=identity.firmware, uuid=identity.uuid, raw=reply.strip()
        )


def build_status(
    replies: dict[str, str], errors: dict[str, str] | None = None, *, host: str = "?"
) -> ZMorphStatus:
    """Turn one round of G-code answers into a machine snapshot.

    A round that produced nothing readable is a protocol error: the host answers,
    but not with what a Zmorph would say.
    """
    print_status: ZMorphPrintStatus | None = (
        parse_m27(replies[M27]) if M27 in replies else None
    )
    temperatures: ZMorphTemperatures | None = (
        parse_m105(replies[M105]) if M105 in replies else None
    )
    position: ZMorphPosition | None = (
        parse_m114(replies[M114]) if M114 in replies else None
    )

    if print_status is None or print_status.state is ZMorphState.UNKNOWN:
        raise ZMorphProtocolError(host, repr(list(replies.values())[:1])[:80])

    return ZMorphStatus(
        online=True,
        print_status=print_status,
        temperatures=temperatures or ZMorphTemperatures(),
        position=position,
        replies=dict(replies),
        errors=dict(errors or {}),
    )


def _looks_like_firmware(answer: str) -> bool:
    """Return whether the answer could come from a RepRap-style controller."""
    if not answer:
        return False
    lowered = answer.lower()
    if lowered.startswith(_HTML_MARKERS):
        return False
    return any(marker in lowered for marker in _FIRMWARE_MARKERS)


def _reason(err: Exception) -> str:
    """Return a short reason for a connection error."""
    if isinstance(err, aiohttp.ServerDisconnectedError):
        return "dropped the connection"
    if isinstance(err, aiohttp.InvalidURL):
        return f"has an address this integration cannot use ({err})"
    os_error = getattr(err, "os_error", None)
    if os_error is not None:
        return str(getattr(os_error, "strerror", None) or os_error)
    message = str(err).strip().lower()
    return message or f"raised {type(err).__name__}"
