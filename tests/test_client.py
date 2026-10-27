"""Tests for the G-code transport."""

from collections.abc import AsyncGenerator
from typing import Any

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.zmorph.client import (
    M27,
    M105,
    M114,
    ZMorphClient,
    ZMorphOffline,
    ZMorphProtocolError,
    machine_unique_id,
)
from custom_components.zmorph.const import COMMAND_PATH

from .const import (
    BASE_URL,
    COMMAND_URL,
    IDENTITY,
    M27_IDLE,
    M27_PRINTING,
    M105_REPLY,
    M114_REPLY,
    M115_REPLY,
    TEST_HOST,
    TEST_PORT,
)


def fake_machine(aioclient_mock: AiohttpClientMocker, answers: dict[str, Any]) -> None:
    """Answer every command of a probe round with its own reply.

    ``answers`` maps a G-code to either the text to answer with, or an exception
    to raise. A command that is not listed stops the round, the way a machine
    that fell asleep mid-round does.
    """

    async def side_effect(
        method: str, url: Any, data: Any
    ) -> AiohttpClientMockResponse:
        command = (data or "").strip()
        answer = answers.get(command)

        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            raise aiohttp.ClientConnectionError("the machine went quiet")
        return AiohttpClientMockResponse(
            method=method, url=url, status=200, text=str(answer)
        )

    aioclient_mock.post(COMMAND_URL, side_effect=side_effect)


@pytest.fixture
async def session(
    aioclient_mock: AiohttpClientMocker,
) -> AsyncGenerator[aiohttp.ClientSession]:
    """Return an HTTP session whose requests the mock answers."""
    async with aioclient_mock.create_session(None) as client_session:
        yield client_session


@pytest.fixture
def client(session: aiohttp.ClientSession) -> ZMorphClient:
    """Return a client for the test machine."""
    return ZMorphClient(session, host=TEST_HOST, port=TEST_PORT)


async def test_command_is_sent_with_its_line_feed(
    client: ZMorphClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """The firmware needs the trailing line feed, so the body must carry it."""
    fake_machine(aioclient_mock, {M105: M105_REPLY})

    reply = await client.send(M105)

    assert reply == M105_REPLY
    method, url, data, headers = aioclient_mock.mock_calls[-1]
    assert method == "POST"
    # yarl drops the default port from the printed URL, so check the parts.
    assert url.host == TEST_HOST
    assert url.path == COMMAND_PATH
    assert data == "M105\n"
    assert headers["Content-Type"] == "text/plain"


async def test_probe_round_sends_every_command(
    client: ZMorphClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """While the machine answers, the whole round is collected."""
    fake_machine(
        aioclient_mock,
        {M27: M27_PRINTING, M105: M105_REPLY, M114: M114_REPLY},
    )

    status = await client.probe()

    assert status.online
    assert status.replies == {M27: M27_PRINTING, M105: M105_REPLY, M114: M114_REPLY}
    assert len(aioclient_mock.mock_calls) == 3
    assert [call[2] for call in aioclient_mock.mock_calls] == [
        "M27\n",
        "M105\n",
        "M114\n",
    ]


async def test_probe_reports_progress_from_the_bytes(
    client: ZMorphClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """The snapshot progress is the byte share of the M27 answer."""
    fake_machine(
        aioclient_mock, {M27: M27_PRINTING, M105: M105_REPLY, M114: M114_REPLY}
    )

    status = await client.probe()

    assert status.progress == pytest.approx(2.6)


async def test_probe_of_an_idle_machine(
    client: ZMorphClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """The idle answer is a real reading, not a failure."""
    fake_machine(aioclient_mock, {M27: M27_IDLE, M105: M105_REPLY, M114: M114_REPLY})

    status = await client.probe()

    assert status.online
    assert status.state.value == "idle"
    assert status.progress is None


async def test_round_keeps_what_arrived_before_the_machine_fell_asleep(
    client: ZMorphClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A machine that stops mid-round keeps the readings that arrived."""
    fake_machine(aioclient_mock, {M27: M27_PRINTING})

    status = await client.probe()

    assert status.online
    assert M27 in status.replies
    assert M105 in status.errors
    # The round stops at the first silence: an off machine is not hammered.
    assert M114 not in status.replies
    assert len(aioclient_mock.mock_calls) == 2


async def test_no_answer_at_all_is_offline(
    client: ZMorphClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A connection failure on the first command means the machine is off."""
    fake_machine(aioclient_mock, {M27: aiohttp.ClientConnectionError("refused")})

    with pytest.raises(ZMorphOffline):
        await client.probe()


async def test_timeout_is_offline(
    client: ZMorphClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A machine that never answers in time is off, not broken."""
    aioclient_mock.post(COMMAND_URL, exc=TimeoutError())

    with pytest.raises(ZMorphOffline):
        await client.send(M27)


async def test_missing_command_endpoint_is_not_a_machine(
    client: ZMorphClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A host with no /command endpoint will never grow one."""
    aioclient_mock.post(COMMAND_URL, status=404, text="not found")

    with pytest.raises(ZMorphProtocolError):
        await client.send(M27)


async def test_a_web_page_is_not_a_machine(
    client: ZMorphClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A router or captive portal answering HTML is reported as the wrong host."""
    aioclient_mock.post(COMMAND_URL, text="<html><body>hello</body></html>")

    with pytest.raises(ZMorphProtocolError):
        await client.send(M27)


async def test_an_empty_answer_is_not_a_machine(
    client: ZMorphClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """An empty body carries no reading, so the round is not usable."""
    aioclient_mock.post(COMMAND_URL, text="")

    with pytest.raises(ZMorphProtocolError):
        await client.send(M27)


async def test_server_error_counts_as_offline(
    client: ZMorphClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 500 from the machine is a machine that is not working: try later."""
    aioclient_mock.post(COMMAND_URL, status=500, text="Internal Server Error")

    with pytest.raises(ZMorphOffline):
        await client.send(M27)


async def test_identity_of_an_awake_machine(
    client: ZMorphClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """M115 gives the firmware and the UUID the machine can be identified by."""
    fake_machine(aioclient_mock, {"M115": M115_REPLY})

    identity = await client.fetch_identity()

    assert identity == IDENTITY


async def test_identity_of_an_off_machine(
    client: ZMorphClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """An off machine has no identity, which is not an error."""
    aioclient_mock.post(COMMAND_URL, exc=aiohttp.ClientConnectionError("refused"))

    identity = await client.fetch_identity()

    assert identity.firmware is None
    assert identity.machine_id is None


@pytest.mark.parametrize(
    ("host", "port", "expected"),
    [
        ("fab", 80, "zmorph:host:fab"),
        ("Fab.LOCAL", 80, "zmorph:fab.local".replace("zmorph:", "zmorph:host:")),
        ("192.0.2.7", 8080, "zmorph:host:192.0.2.7:8080"),
    ],
)
def test_unique_id_of_the_address(host: str, port: int, expected: str) -> None:
    """The address identifies the machine, because the firmware has no serial."""
    assert machine_unique_id(host, port) == expected


def test_base_url_of_the_client(session: aiohttp.ClientSession) -> None:
    """The client builds the endpoint the protocol notes describe."""
    client = ZMorphClient(session, host=TEST_HOST, port=TEST_PORT)

    assert client.base_url == BASE_URL
    assert f"{client.base_url}{COMMAND_PATH}" == COMMAND_URL
