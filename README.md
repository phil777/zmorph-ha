*DISCLAIMER*: 100% vibe-coded; works for me. Use at your own risk.

# Zmorph for Home Assistant

A [HACS](https://hacs.xyz/) custom integration for the **Zmorph Fab**: what the
machine is doing, how hot it is, how far into the file it is, and when Home
Assistant will ask it again.

It talks the protocol the machine really speaks — G-code over one HTTP endpoint —
and it is built around the one fact that matters on a workshop printer: **it is
switched off most of the day**.

```
POST http://fab/command        "M27\n"        ->  SD printing byte 24758/968376
```

## How it deals with a printer that is off

The wait between probes grows while the machine stays silent and collapses back
to the start the moment it answers.

```
silent probe  ->  15s  ->  30s  ->  60s  ->  120s  ->  ...  ->  20 min
machine answers  ->  15s, and every G-code is collected again
```

- Both ends of the ladder are configurable per entry: **Wait between probes**
  (default 15 s) and **Longest wait between probes** (default 1200 s = 20 min).
- The doubling is `x2` per silent probe, capped at the longest wait.
- **Probe now** (a button) sends the round immediately instead of waiting, and
  restarts the ladder from the bottom. It stays available while the printer is
  off, because that is when it is needed.
- An unanswered probe is **not** an error: the log gets one line when the machine
  goes quiet and one when it comes back, not one line every probe.
- A host that answers with something that is not controller output (a router, a
  web server) *is* reported, because no amount of retrying will fix it.

The printer does not have to be on to add the integration. If it is off during
setup, the address becomes the identity of the entry; if it is on, the UUID the
firmware reports in M115 is used instead, since that survives a new name.

## What it shows

| Entity | From | While the printer is off |
| --- | --- | --- |
| `sensor.<name>_state` | M27 | `offline` |
| `sensor.<name>_progress` | M27 bytes / file size | unavailable |
| `sensor.<name>_nozzle_temperature`, `_nozzle_target` | M105 `T:` | unavailable |
| `sensor.<name>_bed_temperature`, `_bed_target` | M105 `B:` | unavailable |
| `sensor.<name>_next_probe` | the probe ladder | the time of the next probe |
| `sensor.<name>_x_position`, `_y_position`, `_z_position` | M114 | off by default |
| `sensor.<name>_bytes_printed`, `_bytes_total` | M27 | off by default |
| `sensor.<name>_probe_wait` | the probe ladder | off by default |
| `button.<name>_probe_now` | — | available, press it |

**Progress is a byte count, not a guess.** The firmware reports neither a
percentage nor a time estimate, so progress is `bytes_printed / bytes_total`,
which for `SD printing byte 24758/968376` is 2.6 %. When the machine is idle the
answer carries no bytes at all, so the state entity says `idle` and progress has
nothing to show. No remaining-time figure is invented anywhere.

The raw text of every answer of the last round is in the diagnostics download,
which is what makes a firmware difference reportable.

## Requirements

| Requirement | Value |
| --- | --- |
| Home Assistant | 2026.10 or newer |
| Python | 3.14.2 or newer, what Home Assistant 2026.10 needs |
| Extra Python packages | none: the client uses the aiohttp session of Home Assistant |
| Machine | on the network, answering G-code on `POST /command` |

## Install

1. In HACS: **Custom repositories** → add `https://github.com/phil777/zmorph-ha` with the category **Integration**.
2. Install **Zmorph**, then restart Home Assistant.
3. **Settings** → **Devices & services** → **Add integration** → `Zmorph`.

[![Add repository with HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=phil777&repository=zmorph-ha&category=integration)

Without HACS: copy `custom_components/zmorph/` into your Home Assistant
`config/custom_components/` directory and restart.

## Configure

| Field | Meaning |
| --- | --- |
| Host | Name or address of the machine. The Fab answers to `fab`, which is the default. |
| Port | Port of its web service. `80` unless you know otherwise. |

The flow sends one round to check the address. No answer is accepted — the
printer is probably off — but an answer that is not G-code is refused.

**Options** (three-dot menu of the entry): the two ends of the probe ladder.
Changing them reloads the entry.

## Layout

```
.github/
  ISSUE_TEMPLATE/     bug report and support forms
  workflows/          CI (ruff, strict mypy, pytest), hassfest, HACS action
  dependabot.yml      keeps the two version pins together
brand/                icon.png and logo.png for the HACS store check
custom_components/
  zmorph/
    __init__.py       set up and unload the entry, store runtime_data
    button.py         the Probe now button
    client.py         G-code over HTTP, and the offline/protocol split  <- device edge
    config_flow.py    address, identity, and the probe ladder options
    const.py          domain, defaults, ladder limits
    coordinator.py    the probe ladder, built on DataUpdateCoordinator
    diagnostics.py    the raw G-code round, for bug reports
    entity.py         base entity, device info, offline availability
    icons.json        entity icons
    manifest.json     domain, version, iot_class
    models.py         the M27 / M105 / M114 / M115 parsers
    sensor.py         readings and the two ladder entities
    strings.json      all user-facing text          <- edit this, not en.json
    translations/
      en.json         generated from strings.json   <- do not hand-edit
docs/DEVICE_API.md    what the machine answers, and what is still unknown
docs/zmorph_fab_protocol.txt   the protocol notes this integration was built on
script/
  probe_machine.py    ask a real machine what it answers (no HA needed)
  sync_translations.py  strings.json -> translations/en.json
tests/                115 tests, 97% coverage
hacs.json             what HACS shows and how it fetches the files
requirements_dev.txt  pins for the dev environment
```

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements_dev.txt

ruff check custom_components tests script      # lint
ruff format --check custom_components tests script
mypy custom_components tests                   # strict typing
pytest -q --cov=custom_components.zmorph       # tests
python script/sync_translations.py             # after editing strings.json
```

Validate the structure the way the store does, with Docker:

```bash
docker run --rm -v "$PWD":/github/workspace ghcr.io/home-assistant/hassfest
```

Three things worth knowing before you change anything:

- **`strings.json` is the source, `translations/en.json` is what ships.** Home
  Assistant reads `strings.json` only for integrations in core; a custom
  integration is served from `translations/<lang>.json`. If it is stale, entities
  arrive named `sensor.fab_2` instead of by name. CI checks it.
- **`async_setup_entry` returns `bool`.** Home Assistant 2026.11 lets config
  entry methods return `None` and raise instead, and core does that now. Home
  Assistant 2026.10 treats a missing boolean as a setup failure, so the boolean
  form keeps this integration installable on the current stable release.
- **`update_interval` is a live property.** The ladder works by setting it after
  every round; `DataUpdateCoordinator` reads it when it schedules the next one.
  Nothing here needs its own timer.

### Run it against a real instance

```bash
hass --config ./config --skip-pip
```

Debug logging for the integration, including every G-code sent and answered:

```yaml
logger:
  default: warning
  logs:
    custom_components.zmorph: debug
```

## Release

1. Bump `version` in `custom_components/zmorph/manifest.json`, update `CHANGELOG.md`.
2. Push, wait for **CI**, **Hassfest** and **HACS** to pass.
3. Create a GitHub **release** (a tag alone is not enough) with the tag equal to
   the version, for example `0.2.0`.

To be listed in the HACS store by default, the repository also needs to be public
with a description and topics, issues enabled, an OSI-approved license, brand
assets, at least one release, and passing HACS and hassfest actions. Then open a
pull request against [`hacs/default`](https://github.com/hacs/default).

## Known unknowns

Documented in [docs/DEVICE_API.md](docs/DEVICE_API.md): what `Q:` and `P:` in the
M105 answer mean, whether every firmware answers `M115`, and whether the endpoint
is safe to hit while Voxelizer owns the machine.

## License

MIT, see [LICENSE](LICENSE).
