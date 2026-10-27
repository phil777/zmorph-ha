# What the machine answers

This integration is built on the protocol notes in
[zmorph_fab_protocol.txt](zmorph_fab_protocol.txt). That file is the ground
truth; this page is what the code does with it, and what is still open.

## The endpoint

One URL, plain text in both directions, no authentication:

```
POST http://fab/command          body: "M27\n"          reply: text
```

The trailing line feed is part of the command. Send `M27` without it and the
firmware keeps waiting for the rest of the line, which is why the notes pipe an
`echo` into `curl --data-binary`. `client.py` sends `f"{command}\n"` for the same
reason, and a test asserts it.

## The commands

| Command | While printing | While idle | Used for |
| --- | --- | --- | --- |
| `M27` | `SD printing byte 24758/968376` | `Not currently playing` | state, progress, byte counts |
| `M105` | `ok T:189.9 /190.0 @111 Q:inf /0.0 @0 P:45.7 /0.0 @0 B:60.0 /60.0 @255` | same shape | temperatures |
| `M114` | `ok C: X:101.0120 Y:152.5530 Z:0.2000 E:21.3844` | same shape | coordinates |
| `M115` | `FIRMWARE_NAME:Marlin ... UUID:...` | same shape | firmware version, and the UUID used as the identity |

`M27`, `M105` and `M114` are one round. `M115` is read once when the entry is set
up, because nothing about it changes between probes.

### Progress

`M27` reports a byte position, not a percentage and no time. Progress is
therefore arithmetic in the integration:

```
24758 / 968376 * 100 = 2.6 %
```

Idle has no byte position at all, so it has no progress: the state entity says
`idle`, and the progress entity has nothing to show. Nothing in the code
invents an ETA.

### Temperatures

`T` is the extruder and `B` the bed, each as `current /target`. The `@` values
are heater power and are ignored.

`Q` and `P` also appear in the answer. Their meaning is not documented, so the
parser keeps them under their letter in `ZMorphTemperatures.other` and they show
up in diagnostics rather than being renamed into a guess. `Q:inf` is dropped
rather than plotted: `inf` is not a temperature.

### Identity

The machine reports no serial number. Marlin's `M115` sometimes carries a `UUID`,
which is the best handle available, so:

- firmware answered with a UUID → the entry is `zmorph:uuid:<uuid>`
- machine was off while it was added → the entry is `zmorph:host:<host>[:<port>]`

An address-identified entry is upgraded to its UUID the first time a reconfigure
reaches the machine. A UUID-identified entry refuses an address that answers with
a different UUID: that is another printer, and taking it over would move every
entity of the real machine onto a different one.

## Offline, and how the code tells the three outcomes apart

| Outcome | What happened | What the code does |
| --- | --- | --- |
| `ZMorphOffline` | connection refused, DNS failure, timeout, 5xx | snapshot says offline, ladder doubles, one log line |
| answer, not G-code | HTML page, empty body | `ZMorphProtocolError`, entry reports it: the address is wrong |
| `404` on `/command` | a web server that is not the machine | `ZMorphProtocolError`, since it will never grow the endpoint |

The distinction matters because an off machine is the normal state. Raising on it
would put an error in the log every probe and mark the entry as failing; instead
the round returns an offline snapshot, and only a genuinely wrong host is an
error.

Mid-round silence is not fatal: if `M27` answers and the machine goes quiet
afterwards, the round keeps what arrived and records the rest in `errors`.

## Still unknown

1. **`Q:` and `P:`** in the M105 answer. Uninterpreted on purpose. If you know
   what they are, they become two sensor descriptions and two strings.
2. **Does every firmware answer `M115`?** The integration works without it
   (identity falls back to the address), but it is unverified on older boards.
   `python3 script/probe_machine.py fab --command M115` tells you in one second.
3. **Is the endpoint free to share with Voxelizer?** The machine answers G-code
   while the desktop application may hold the serial link. If the two conflict,
   the integration should say so in the docs and probe even more conservatively.
4. **`HTTPS`?** The client speaks plain HTTP: this is a LAN endpoint on a machine
   with no certificate. If a firmware serves it, `base_url` is one line.
5. **Idle vs no card.** `Not currently playing`, `No card` and `Card detached`
   all read as idle. A machine with no card is not really the same as an idle one;
   if that distinction matters to you, it is a new `ZMorphState` member.

## Changing or adding a command

1. Add the constant and the parser in `models.py`, plus a test using a captured
   answer.
2. Add the command to `PROBE_COMMANDS` in `client.py` if it belongs to the round.
3. Add one entity description in `sensor.py`, a name in `strings.json`, an icon in
   `icons.json`.
4. `python3 script/sync_translations.py`, then `pytest -q`.

Nothing else needs to change: the coordinator, the ladder, availability and
diagnostics follow automatically.
