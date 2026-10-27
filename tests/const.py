"""Sample data for the Zmorph tests, taken from docs/zmorph_fab_protocol.txt."""

from custom_components.zmorph.models import (
    ZMorphIdentity,
    ZMorphPosition,
    ZMorphPrintStatus,
    ZMorphState,
    ZMorphStatus,
    ZMorphTemperatures,
)

TEST_HOST = "fab"
TEST_PORT = 80
# Both identity forms: the address, and the UUID a Marlin board can report.
TEST_UNIQUE_ID = "zmorph:host:fab"
# The id is lowercased, so a firmware that reports the UUID in another
# case still lands on the same entry.
TEST_UUID_UNIQUE_ID = "zmorph:uuid:32333351353251002a20205019002f53"
OTHER_UUID_UNIQUE_ID = "zmorph:uuid:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
TEST_TITLE = "fab"

BASE_URL = f"http://{TEST_HOST}:{TEST_PORT}"
COMMAND_URL = f"{BASE_URL}/command"

# The exact answers of the protocol notes.
M27_PRINTING = "SD printing byte 24758/968376\nok\n"
M27_IDLE = "Not currently playing\n"
M105_REPLY = "ok T:189.9 /190.0 @111 Q:inf /0.0 @0 P:45.7 /0.0 @0 B:60.0 /60.0 @255\n"
M114_REPLY = "ok C: X:101.0120 Y:152.5530 Z:0.2000 E:21.3844\n"
M115_REPLY = (
    "FIRMWARE_NAME:Marlin 2.1.2.4 (Github) SOURCE_CODE_URL:https://github.com/"
    "MarlinFirmware/Marlin PROTOCOL_VERSION:1.0 MACHINE_TYPE:Zmorph_Fab "
    "EXTRUDER_CODE:M105 UUID:32333351353251002A20205019002F53\nok\n"
)

REPLIES = {
    "M27": M27_PRINTING,
    "M105": M105_REPLY,
    "M114": M114_REPLY,
}

# 24758 of 968376 bytes is 2.6 percent.
EXPECTED_PROGRESS = 2.6

PRINTING = ZMorphPrintStatus(
    state=ZMorphState.PRINTING, bytes_printed=24758, bytes_total=968376
)
TEMPERATURES = ZMorphTemperatures(
    nozzle=189.9,
    nozzle_target=190.0,
    bed=60.0,
    bed_target=60.0,
    other={"Q": (None, 0.0), "P": (45.7, 0.0)},
)
POSITION = ZMorphPosition(x=101.0120, y=152.5530, z=0.2000, e=21.3844)
IDENTITY = ZMorphIdentity(
    firmware="Marlin 2.1.2.4 (Github)",
    uuid="32333351353251002A20205019002F53",
    raw=M115_REPLY.strip(),
)

ONLINE_STATUS = ZMorphStatus(
    online=True,
    print_status=PRINTING,
    temperatures=TEMPERATURES,
    position=POSITION,
    replies=dict(REPLIES),
)

IDLE_STATUS = ZMorphStatus(
    online=True,
    print_status=ZMorphPrintStatus(state=ZMorphState.IDLE),
    temperatures=TEMPERATURES,
    position=POSITION,
    replies={"M27": M27_IDLE, "M105": M105_REPLY, "M114": M114_REPLY},
)

USER_INPUT = {"host": TEST_HOST, "port": TEST_PORT}
