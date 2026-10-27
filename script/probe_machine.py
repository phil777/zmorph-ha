#!/usr/bin/env python3
"""Ask a Zmorph machine what it actually answers.

The integration talks G-code over one HTTP endpoint. This script sends the same
requests and prints the raw text, so you can check a machine, a firmware version,
or a different address without touching Home Assistant.

It is standalone and needs only ``aiohttp``::

    python3 script/probe_machine.py fab
    python3 script/probe_machine.py 192.168.1.50 --ports 80,8080
    python3 script/probe_machine.py fab --command M115
    python3 script/probe_machine.py fab --json > fab-round.json

Only the commands you list are sent. They are read-only by default.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

import aiohttp

# Read-only G-code: status, temperatures, coordinates, firmware.
DEFAULT_COMMANDS = ["M27", "M105", "M114", "M115"]

COMMAND_PATH = "/command"


async def send(
    session: aiohttp.ClientSession, base: str, command: str, timeout: float
) -> dict[str, Any]:
    """Send one G-code and describe the answer."""
    entry: dict[str, Any] = {"command": command}
    try:
        async with session.post(
            f"{base}{COMMAND_PATH}",
            # The line feed terminates the command for the firmware.
            data=f"{command}\n",
            headers={"Content-Type": "text/plain"},
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as response:
            text = await response.text()
            entry["status"] = response.status
            entry["reply"] = text.strip()
    except aiohttp.ClientError as err:
        entry["status"] = "no answer"
        entry["error"] = f"{type(err).__name__}: {err}"
    except TimeoutError:
        entry["status"] = "timeout"
    return entry


def classify(entry: dict[str, Any]) -> str:
    """Return a one-word verdict for one answer."""
    reply = entry.get("reply", "")
    lowered = reply.lower()

    if entry["status"] in ("no answer", "timeout"):
        return "OFFLINE"
    if entry["status"] == 404:
        return "NO_ENDPOINT"
    if lowered.startswith(("<!doctype", "<html", "<?xml")):
        return "NOT_A_MACHINE"
    # The needles are lowercase: the haystack already is.
    if "sd printing byte" in lowered:
        return "PRINTING"
    if "not currently playing" in lowered:
        return "IDLE"
    if "firmware_name" in lowered:
        return "FIRMWARE"
    if lowered.startswith("ok") or "t:" in lowered:
        return "CONTROLLER"
    if "error" in lowered:
        return "REFUSED"
    return "UNEXPECTED"


def report(host: str, port: int, results: list[dict[str, Any]]) -> None:
    """Print the round and what it means."""
    print(f"\n=== {host}:{port} ===")

    for entry in results:
        verdict = classify(entry)
        answer = entry.get("reply") or entry.get("error") or ""
        print(f"  {entry['command']:<5} {verdict:<15} status={entry['status']}")
        if answer:
            print(f"        {answer[:200]}")

    if all(classify(entry) == "OFFLINE" for entry in results):
        print("\n  Nothing answered. Either the machine is off, or it is not at")
        print("  this address. Switch it on and try again; the integration copes")
        print("  with this state, but you cannot confirm the protocol from it.")
        return

    if any(classify(entry) == "NOT_A_MACHINE" for entry in results):
        print("\n  Something answered, but with a web page rather than G-code.")
        print("  This address is not the machine's command endpoint.")
        return

    if any(classify(entry) == "NO_ENDPOINT" for entry in results):
        print(f"\n  The host has no {COMMAND_PATH} endpoint. Check the port, or")
        print("  whether this firmware exposes the command interface at all.")
        return

    identity = next((entry for entry in results if entry["command"] == "M115"), None)
    if (
        identity
        and identity.get("status") == 200
        and "UUID" in identity.get("reply", "")
    ):
        print("\n  M115 reports a UUID, so the entry will be identified by it")
        print("  rather than by its address.")
    else:
        print("\n  No UUID in the M115 answer: the entry will be identified by its")
        print("  address. That works, but a new name for the machine makes it look")
        print("  like a new device.")


async def run(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Probe every requested port and print what came back."""
    all_results: dict[str, list[dict[str, Any]]] = {}

    async with aiohttp.ClientSession() as session:
        for port in args.ports:
            base = f"http://{args.host}:{port}"
            results = [
                await send(session, base, command, args.timeout)
                for command in args.commands
            ]
            all_results[base] = results
            if not args.json:
                report(args.host, port, results)

    if args.json:
        print(json.dumps(all_results, indent=2))

    return [entry for results in all_results.values() for entry in results]


def parse_args() -> argparse.Namespace:
    """Read the command line."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("host", help="Name or address of the machine, e.g. fab")
    parser.add_argument(
        "--ports",
        type=lambda value: [int(part) for part in value.split(",")],
        default=[80],
        help="Comma separated ports (default: 80)",
    )
    parser.add_argument(
        "--command",
        dest="commands",
        action="append",
        help="G-code to send; repeat for several (default: M27 M105 M114 M115)",
    )
    parser.add_argument(
        "--timeout", type=float, default=5.0, help="Seconds per request (default: 5)"
    )
    parser.add_argument(
        "--json", action="store_true", help="Print the raw findings as JSON"
    )
    args = parser.parse_args()
    if not args.commands:
        args.commands = list(DEFAULT_COMMANDS)
    return args


def main() -> int:
    """Run the probe."""
    asyncio.run(run(parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
