#!/usr/bin/env python3
"""Build ``translations/en.json`` from ``strings.json``.

Home Assistant reads ``strings.json`` only for integrations in core. A custom
integration is served from ``custom_components/<domain>/translations/en.json``,
so that file has to exist in the repository, and HACS has to ship it.

``strings.json`` stays the single source of truth. This script copies it to
``translations/en.json`` and resolves every ``[%key:...%]`` reference against
the shared strings of the installed Home Assistant, exactly like the core build
does.

Usage::

    python3 script/sync_translations.py           # write the file
    python3 script/sync_translations.py --check    # fail when it is stale

``--check`` belongs in CI: a stale ``translations/en.json`` means users see
entity ids instead of names.
"""

from __future__ import annotations

import argparse
import importlib.resources
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOMAIN = "zmorph"
STRINGS = ROOT / "custom_components" / DOMAIN / "strings.json"
TARGET = ROOT / "custom_components" / DOMAIN / "translations" / "en.json"

KEY_PATTERN = re.compile(r"\[%key:(.+?)%\]")


def resolve(reference: str, common: dict) -> str:
    """Return the text a ``[%key:...]`` reference points at."""
    node = common
    for part in reference.split("::"):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(f"Unknown translation reference: {reference}")
        node = node[part]
    if not isinstance(node, str):
        raise TypeError(f"Reference {reference} does not point at a string")
    return node


def translate(value, common: dict):
    """Return value with every translation reference replaced."""
    if isinstance(value, dict):
        return {key: translate(item, common) for key, item in value.items()}
    if isinstance(value, list):
        return [translate(item, common) for item in value]
    if isinstance(value, str):
        return KEY_PATTERN.sub(lambda m: resolve(m.group(1), common), value)
    return value


def build() -> str:
    """Return the contents of translations/en.json."""
    common = json.loads(
        importlib.resources.files("homeassistant")
        .joinpath("strings.json")
        .read_text(encoding="utf-8")
    )
    strings = json.loads(STRINGS.read_text(encoding="utf-8"))
    return json.dumps(translate(strings, common), indent=2, sort_keys=True) + "\n"


def main() -> int:
    """Write or check the generated file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when translations/en.json is not up to date",
    )
    args = parser.parse_args()

    expected = build()

    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != expected:
            print(
                f"{TARGET.relative_to(ROOT)} is stale. "
                "Run: python3 script/sync_translations.py",
                file=sys.stderr,
            )
            return 1
        print(f"{TARGET.relative_to(ROOT)} is up to date.")
        return 0

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(expected, encoding="utf-8")
    print(f"Wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
