import pytest

from ptzsim import state as st
from ptzsim.visca import ViscaCamera, decode_nibbles, encode_nibbles, parse_hex, split_packets

ACK = parse_hex("90 41 FF")
DONE = parse_hex("90 51 FF")
SYNTAX_ERROR = parse_hex("90 60 02 FF")
NOT_EXECUTABLE = parse_hex("90 61 41 FF")


def send(cam, text):
    return [r.data for r in cam.handle(parse_hex(text))]


@pytest.fixture
def cam():
    return ViscaCamera(instant=True)


def test_nibble_roundtrip_signed():
    assert encode_nibbles(-2448) == bytes([0x0F, 0x06, 0x07, 0x00])
    assert decode_nibbles(bytes([0x0F, 0x06, 0x07, 0x00]), signed=True) == -2448
    assert decode_nibbles(encode_nibbles(1296), signed=True) == 1296


def test_split_packets_keeps_partial_tail():
    buffer = bytearray(parse_hex("81 01 06 04 FF 81 09 06"))
    assert split_packets(buffer) == [parse_hex("81 01 06 04 FF")]
    assert buffer == bytearray(parse_hex("81 09 06"))


def test_absolute_position_and_inquiry(cam):
    assert send(cam, "81 01 06 02 18 14 0F 06 07 00 00 05 01 00 FF") == [ACK, DONE]
    assert cam.state.position()[:2] == (-2448, 1296)
    assert send(cam, "81 09 06 12 FF") == [parse_hex("90 50 0F 06 07 00 00 05 01 00 FF")]


def test_absolute_position_is_clamped(cam):
    send(cam, "81 01 06 02 18 14 07 0F 0F 0F 07 0F 0F 0F FF")
    assert cam.state.position()[:2] == (st.PAN_MAX, st.TILT_MAX)


def test_relative_move(cam):
    send(cam, "81 01 06 02 18 14 00 01 00 00 00 00 00 00 FF")  # pan 256
    send(cam, "81 01 06 03 18 14 0F 0F 0F 00 00 00 01 00 FF")  # pan -16, tilt +16
    assert cam.state.position()[:2] == (240, 16)


def test_home(cam):
    send(cam, "81 01 06 02 18 14 00 01 00 00 00 00 01 00 FF")
    assert send(cam, "81 01 06 04 FF") == [ACK, DONE]
    assert cam.state.position()[:2] == (0, 0)


def test_drive_sets_velocity_and_stop_clears_it(cam):
    send(cam, "81 01 06 01 0C 0A 02 01 FF")  # right + up
    assert cam.state.pan_velocity > 0 and cam.state.tilt_velocity > 0
    cam.state.tick(0.5)
    assert cam.state.pan > 0 and cam.state.tilt > 0
    send(cam, "81 01 06 01 0C 0A 03 03 FF")
    assert cam.state.pan_velocity == cam.state.tilt_velocity == 0


def test_drive_stops_at_limit():
    s = st.CameraState()
    s.drive_pan_tilt(-1, 0, st.PAN_SPEED_MAX, 1)
    s.tick(100)
    assert s.pan == st.PAN_MIN and s.pan_velocity == 0


def test_zoom_direct_and_inquiry(cam):
    assert send(cam, "81 01 04 47 02 00 00 00 FF") == [ACK, DONE]
    assert send(cam, "81 09 04 47 FF") == [parse_hex("90 50 02 00 00 00 FF")]


def test_zoom_variable_tele_and_wide():
    cam = ViscaCamera()
    send(cam, "81 01 04 07 27 FF")
    cam.state.tick(1)
    assert cam.state.zoom > 0
    send(cam, "81 01 04 07 00 FF")
    zoom = cam.state.zoom
    cam.state.tick(1)
    assert cam.state.zoom == zoom


def test_focus_mode(cam):
    assert send(cam, "81 09 04 38 FF") == [parse_hex("90 50 02 FF")]
    send(cam, "81 01 04 38 03 FF")
    assert send(cam, "81 09 04 38 FF") == [parse_hex("90 50 03 FF")]
    send(cam, "81 01 04 38 10 FF")
    assert cam.state.autofocus


def test_presets_set_recall_reset(cam):
    send(cam, "81 01 06 02 18 14 00 01 00 00 00 00 02 00 FF")
    send(cam, "81 01 04 47 01 00 00 00 FF")
    assert send(cam, "81 01 04 3F 01 05 FF") == [ACK, DONE]
    send(cam, "81 01 06 04 FF")
    send(cam, "81 01 04 47 00 00 00 00 FF")

    assert send(cam, "81 01 04 3F 02 05 FF") == [ACK, DONE]
    assert cam.state.position()[:3] == (256, 32, 0x1000)
    assert send(cam, "81 09 04 3F FF") == [parse_hex("90 50 05 FF")]

    send(cam, "81 01 04 3F 00 05 FF")
    assert send(cam, "81 01 04 3F 02 05 FF") == [NOT_EXECUTABLE]


def test_power_standby_blocks_motion(cam):
    assert send(cam, "81 01 04 00 03 FF") == [ACK, DONE]
    assert send(cam, "81 09 04 00 FF") == [parse_hex("90 50 03 FF")]
    assert send(cam, "81 01 06 04 FF") == [NOT_EXECUTABLE]
    send(cam, "81 01 04 00 02 FF")
    assert send(cam, "81 01 06 04 FF") == [ACK, DONE]


def test_errors(cam):
    assert send(cam, "81 01 06 77 FF") == [SYNTAX_ERROR]
    assert send(cam, "81 01 06 01 00 0A 02 01 FF") == [SYNTAX_ERROR]  # speed 0
    assert send(cam, "81 01 06 02 18 FF") == [SYNTAX_ERROR]  # truncated
    assert send(cam, "81 09 7E FF") == [SYNTAX_ERROR]
    assert not cam.log[-1].ok


def test_other_address_is_ignored(cam):
    assert send(cam, "82 01 06 04 FF") == []


def test_broadcasts(cam):
    assert send(cam, "88 30 01 FF") == [parse_hex("88 30 02 FF")]
    assert send(cam, "88 01 00 01 FF") == [parse_hex("88 01 00 01 FF")]


def test_camera_address_changes_reply_header():
    cam = ViscaCamera(address=2, instant=True)
    assert send(cam, "82 01 06 04 FF") == [parse_hex("A0 41 FF"), parse_hex("A0 51 FF")]


def test_version_inquiry(cam):
    reply = send(cam, "81 09 00 02 FF")[0]
    assert reply[:2] == b"\x90\x50" and len(reply) == 10


def test_completion_waits_for_motion():
    cam = ViscaCamera()
    replies = cam.handle(parse_hex("81 01 06 02 01 01 00 01 00 00 00 00 00 00 FF"))
    assert [r.after_motion for r in replies] == [False, True]
    assert cam.state.busy
    for _ in range(100):
        cam.state.tick(0.1)
    assert not cam.state.busy and cam.state.position()[0] == 256
