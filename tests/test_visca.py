# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

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


def test_white_balance_modes_and_one_push(cam):
    assert send(cam, "81 09 04 35 FF") == [parse_hex("90 50 00 FF")]
    assert send(cam, "81 01 04 35 05 FF") == [ACK, DONE]
    assert send(cam, "81 09 04 35 FF") == [parse_hex("90 50 05 FF")]
    assert send(cam, "81 01 04 35 01 FF") == [ACK, DONE]
    assert cam.state.white_balance == "indoor"
    assert send(cam, "81 01 04 35 0A FF") == [SYNTAX_ERROR]
    cam.state.red_gain = 0x40
    assert send(cam, "81 01 04 10 05 FF") == [ACK, DONE]
    assert cam.state.white_balance == "manual"
    assert (cam.state.red_gain, cam.state.blue_gain) == (st.WB_GAIN_NEUTRAL, st.WB_GAIN_NEUTRAL)


def test_preset_numbers_follow_sony_range(cam):
    # "00 to 63" in the Sony list is hex: 100 presets, 0x00..0x63
    assert send(cam, "81 01 04 3F 01 63 FF") == [ACK, DONE]
    assert send(cam, "81 01 04 3F 01 64 FF") == [SYNTAX_ERROR]


def test_preset_speed_commands_and_inquiries(cam):
    assert send(cam, "81 01 7E 04 1C 00 0A FF") == [ACK, DONE]
    assert send(cam, "81 09 7E 04 1C FF") == [parse_hex("90 50 00 0A FF")]
    assert send(cam, "81 01 7E 04 1B 02 FF") == [ACK, DONE]
    assert send(cam, "81 09 7E 04 1B FF") == [parse_hex("90 50 02 FF")]
    assert send(cam, "81 01 7E 01 0B 05 07 FF") == [ACK, DONE]
    assert send(cam, "81 09 7E 01 0B 05 FF") == [parse_hex("90 50 07 FF")]
    assert send(cam, "81 01 7E 01 0B 05 33 FF") == [SYNTAX_ERROR]
    assert send(cam, "81 01 7E 04 1C 00 00 FF") == [SYNTAX_ERROR]


def test_recall_uses_preset_speed_settings():
    s = st.CameraState()
    s.pan = 1000
    s.save_preset(0)
    s.pan = 0
    s.preset_speeds[0] = 25
    s.recall_preset(0)
    assert s.pan_target[1] == pytest.approx(st.PAN_SPEED_MAX * 0.5 * st.PAN_TILT_UNITS_PER_SPEED_STEP)
    s.preset_speed_mode = "common"
    s.common_preset_speed = st.PRESET_SPEED_MAX
    s.recall_preset(0)
    assert s.pan_target[1] == pytest.approx(st.PAN_SPEED_MAX * st.PAN_TILT_UNITS_PER_SPEED_STEP)


def test_red_and_blue_gain_commands(cam):
    assert send(cam, "81 01 04 43 00 00 00 05 FF") == [ACK, DONE]
    assert cam.state.red_gain == 5
    assert send(cam, "81 01 04 03 02 FF") == [ACK, DONE]
    assert cam.state.red_gain == 5 + st.WB_GAIN_STEP
    assert send(cam, "81 01 04 44 00 00 0F 0F FF") == [ACK, DONE]
    assert cam.state.blue_gain == st.WB_GAIN_MAX
    assert send(cam, "81 01 04 44 01 00 00 00 FF") == [SYNTAX_ERROR]
    assert send(cam, "81 01 04 04 00 FF") == [ACK, DONE]
    assert cam.state.blue_gain == st.WB_GAIN_NEUTRAL


def test_pan_tilt_status_reports_end_stops(cam):
    # Sony "Pan/Tilt Status Codes": 0x2000 = initialization completes
    assert send(cam, "81 09 06 10 FF") == [parse_hex("90 50 20 00 FF")]
    cam.state.pan, cam.state.tilt = st.PAN_MIN, st.TILT_MIN
    assert send(cam, "81 09 06 10 FF") == [parse_hex("90 50 20 09 FF")]
    cam.state.pan, cam.state.tilt = st.PAN_MAX, st.TILT_MAX
    assert send(cam, "81 09 06 10 FF") == [parse_hex("90 50 20 06 FF")]


def test_pan_tilt_status_operating_and_complete():
    cam = ViscaCamera()
    send(cam, "81 01 06 01 10 10 02 03 FF")
    assert send(cam, "81 09 06 10 FF") == [parse_hex("90 50 24 00 FF")]  # operating
    send(cam, "81 01 06 01 10 10 03 03 FF")
    assert send(cam, "81 09 06 10 FF") == [parse_hex("90 50 28 00 FF")]  # complete


def test_if_clear_has_no_ack(cam):
    assert send(cam, "81 01 00 01 FF") == [parse_hex("90 50 FF")]


def test_absolute_tilt_speed_00_follows_pan(cam):
    assert send(cam, "81 01 06 02 18 00 00 01 00 00 00 00 00 00 FF") == [
        parse_hex("90 41 FF"), parse_hex("90 51 FF")]
    assert cam.state.pan == 256


def test_absolute_position_with_five_digits(cam):
    # newer Sony models (e.g. ILME-FR7) use 5 nibbles per axis
    send(cam, "81 01 06 02 18 14 00 00 01 00 00 0F 0F 0F 0F 0F FF")
    assert cam.state.position()[:2] == (256, -1)


def test_max_speed_inquiry(cam):
    assert send(cam, "81 09 06 11 FF") == [parse_hex("90 50 18 17 FF")]


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


def test_manual_focus_is_not_executable_in_auto_focus(cam):
    # Sony VISCA Command List, "Command Not Executable": manual focus during AF
    assert send(cam, "81 01 04 08 02 FF") == [NOT_EXECUTABLE]
    assert send(cam, "81 01 04 48 01 00 00 00 FF") == [NOT_EXECUTABLE]
    assert send(cam, "81 01 04 08 00 FF") == [ACK, DONE]  # stop is harmless
    send(cam, "81 01 04 38 03 FF")
    assert send(cam, "81 01 04 48 01 00 00 00 FF") == [ACK, DONE]
    assert cam.state.position()[3] == 0x1000


def test_address_set_takes_the_address_and_passes_the_next_on():
    cam = ViscaCamera(address=3)
    assert send(cam, "88 30 01 FF") == [parse_hex("88 30 02 FF")]
    assert cam.address == 1
    assert send(cam, "81 01 06 04 FF") == [parse_hex("90 41 FF"), parse_hex("90 51 FF")]
    assert send(cam, "83 01 06 04 FF") == []


def test_two_sockets_then_buffer_full():
    cam = ViscaCamera()
    pan = cam.handle(parse_hex("81 01 06 02 01 01 00 01 00 00 00 00 00 00 FF"))
    zoom = cam.handle(parse_hex("81 01 04 47 04 00 00 00 FF"))
    assert [r.data for r in pan] == [parse_hex("90 41 FF"), parse_hex("90 51 FF")]
    assert [r.data for r in zoom] == [parse_hex("90 42 FF"), parse_hex("90 52 FF")]
    assert zoom[1].axes == frozenset({"zoom"})
    # both sockets busy: "Command Buffer Full" with socket 0
    assert send(cam, "81 01 04 38 03 FF") == [parse_hex("90 60 03 FF")]
    # inquiries and IF_Clear do not use a socket
    assert send(cam, "81 09 04 00 FF") == [parse_hex("90 50 02 FF")]
    assert send(cam, "81 01 00 01 FF") == [parse_hex("90 50 FF")]
    assert send(cam, "81 01 04 38 03 FF") == [ACK, DONE]


def test_cancel_with_invalid_socket(cam):
    assert send(cam, "81 23 FF") == [parse_hex("90 63 05 FF")]
