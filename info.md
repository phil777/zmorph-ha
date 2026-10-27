# Zmorph for Home Assistant

See what your **Zmorph Fab** is doing from Home Assistant: whether it is printing,
how far into the file it is, how hot the nozzle and the bed are, and where the
head is.

## It is built for a printer that is off

The machine is switched off most of the day, so the integration probes it on a
ladder instead of a fixed timer:

- the wait starts at 15 seconds and doubles with every probe that reaches nothing
- it stops growing at 20 minutes, whatever the machine does
- the moment it answers, the wait is 15 seconds again and every reading is collected
- **Probe now** sends the round immediately, and it stays available while the
  printer is off, because that is when you need it

The printer does not have to be on when you add it.

## What you get

- **State**: idle, printing, or offline.
- **Progress**: the share of the file printed, from the byte count the firmware
  reports. No invented time estimate; when it is idle, it says so.
- **Temperatures**: nozzle and bed, current and target.
- **Coordinates** and raw byte counts, as diagnostic entities you can switch on.
- **Next probe**: when Home Assistant will ask again, so the waiting is visible.

One device, so it groups cleanly on the dashboard and in automations. Names,
states and icons come from the translation files.

## Requirements

Home Assistant 2026.10 or newer, and a machine answering G-code on the network
(`POST http://fab/command`). No authentication, no cloud, no extra Python
packages.

## Documentation

Installation, configuration, the entity list and the protocol notes:
[README.md](https://github.com/phil777/zmorph-ha#readme).
