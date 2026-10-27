# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/).

## 0.2.0

The integration now speaks the machine: G-code over one HTTP endpoint, and a
probe schedule built around a printer that is off most of the day.

### Added

- G-code transport: `POST http://fab/command` with the command and its trailing
  line feed, plain-text answers.
- Parsers for `M27` (byte position or idle), `M105` (extruder and bed), `M114`
  (coordinates) and `M115` (firmware and UUID), each forgiving about an answer it
  cannot read.
- Progress derived from the bytes printed over the file size. No invented time
  remaining anywhere.
- A probe ladder: the wait doubles from a configurable start (15 s by default)
  up to a configurable ceiling (1200 s by default) while the machine stays
  silent, and drops back to the start the moment it answers.
- Options to configure both ends of the ladder, validated in the dialog.
- A `Probe now` button that sends the round immediately and restarts the ladder.
  It stays available while the printer is off.
- `Next probe` sensor, so the waiting is visible; `Probe wait` and the raw byte
  counts and coordinates are available as diagnostic entities, off by default.
- Identity by firmware UUID when the machine reports one, falling back to the
  address when it was off during setup.
- Diagnostics carrying the raw text of the last round, the ladder state and the
  firmware identity.
- `script/probe_machine.py`, to ask a real machine what it answers without
  Home Assistant.

### Changed

- Adding the machine no longer requires it to be switched on. A missing answer is
  accepted; an answer that is not controller output is refused, and named.
- No API key, and no reauthentication flow: the endpoint has no authentication.
- Removed the invented 0.1.0 surface: the JSON client, the toolhead and progress
  sensors that came from it, the fume extraction switch, and the home, pause and
  resume buttons.

## 0.1.0

### Added

- First scaffold: config flow, coordinator, description-driven sensors, switch and
  buttons, options flow, diagnostics, tests, and CI.
