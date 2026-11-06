# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Tests for the Pelco-D protocol (7-byte serial frames on the shared camera)."""

import asyncio
import os

import pytest

from ptzsim import state as st
from ptzsim.pelco import (FOCUS_FAR, PAN_LEFT, PAN_RIGHT, PelcoCamera, TILT_DOWN, TILT_UP,
                          ZOOM_TELE, ZOOM_WIDE, checksum, make_frame, split_frames)
from ptzsim.testing import serve
from ptzsim.visca import ViscaCamera


def make(address: int = 1):
    camera = ViscaCamera(instant=True)
    return PelcoCamera(camera, address), camera


def run(pelco: PelcoCamera, frame: bytes):
    replies = []
    pelco.process(frame, replies.append)
    return replies


# ------------------------------------------------------------- frame format
def test_checksum_is_sum_of_bytes_2_to_6():
    # FF 01 00 02 20 00 23: 01+00+02+20+00 = 0x23
    assert checksum(make_frame(1, 0x00, 0x02, 0x20, 0x00)[:-1]) == 0x23
    assert make_frame(1, 0x00, 0x02, 0x20, 0x00) == bytes.fromhex("FF 01 00 02 20 00 23")


def test_split_frames_resyncs_on_the_sync_byte():
    buffer = bytearray(b"\x00\x11" + make_frame(1, 0x00, 0x00, 0x00, 0x00))
    assert split_frames(buffer) == [make_frame(1, 0x00, 0x00, 0x00, 0x00)]
    assert not buffer  # garbage without a sync byte is dropped
    buffer.extend(b"\x42" + make_frame(2, 0x00, 0x03, 0x00, 0x05))
    assert split_frames(buffer) == [make_frame(2, 0x00, 0x03, 0x00, 0x05)]
    # an incomplete frame stays buffered until the rest arrives
    buffer.extend(make_frame(3, 0x00, 0x00, 0x00, 0x00)[:4])
    assert split_frames(buffer) == []
    buffer.extend(make_frame(3, 0x00, 0x00, 0x00, 0x00)[4:])
    assert split_frames(buffer) == [make_frame(3, 0x00, 0x00, 0x00, 0x00)]


def test_split_frames_resyncs_after_a_stray_sync_byte():
    # a stray 0xFF before a valid frame must not swallow it: the invalid
    # 7-byte candidate is dropped byte by byte, the real frame survives
    valid = make_frame(1, 0x00, PAN_RIGHT, 0x20, 0x00)  # FF 01 00 02 20 00 23
    buffer = bytearray(b"\xFF" + valid)
    assert split_frames(buffer) == [valid]
    assert not buffer


def test_wrong_checksum_gets_no_reply():
    pelco, camera = make()
    frame = bytearray(make_frame(1, 0x00, PAN_RIGHT, 0x20, 0x00))
    frame[-1] ^= 0xFF
    assert run(pelco, bytes(frame)) == []
    assert pelco.state.pan_velocity == 0.0
    assert not camera.log[-1].ok


def test_frame_for_another_address_stays_silent():
    pelco, camera = make(address=1)
    assert run(pelco, make_frame(2, 0x00, PAN_RIGHT, 0x20, 0x00)) == []
    assert pelco.state.pan_velocity == 0.0
    assert not camera.log  # not even logged: on the bus nobody answers


# ------------------------------------------------------------------- driving
def test_general_response_is_4_bytes_with_the_request_checksum():
    pelco, _ = make(address=7)
    frame = make_frame(7, 0x00, PAN_RIGHT, 0x20, 0x00)  # FF 07 00 02 20 00 29
    assert pelco.ack(frame) == bytes([0xFF, 7, 0x00, 0x29])
    # the response echoes command 1 (e.g. 0x01 for focus near)
    assert pelco.ack(make_frame(7, 0x01, 0x00, 0x00, 0x00)) == bytes([0xFF, 7, 0x01, 0x08])


def test_pan_right_at_medium_speed():
    pelco, camera = make()
    frame = make_frame(1, 0x00, PAN_RIGHT, 0x20, 0x00)
    assert run(pelco, frame) == [pelco.ack(frame)]  # FF 01 00 23
    # 0x20 = 32 of 0x3F -> round(32 * 24 / 63) = 12 VISCA speed steps
    assert pelco.state.pan_velocity == 12 * st.PAN_TILT_UNITS_PER_SPEED_STEP
    assert pelco.state.tilt_velocity == 0.0
    assert "pan right" in camera.log[-1].description


def test_tilt_down_turbo_and_combined_move():
    pelco, _ = make()
    run(pelco, make_frame(1, 0x00, TILT_DOWN | PAN_LEFT, 0xFF, 0x3F))
    assert pelco.state.tilt_velocity == -st.TILT_SPEED_MAX * st.PAN_TILT_UNITS_PER_SPEED_STEP
    assert pelco.state.pan_velocity == -st.PAN_SPEED_MAX * st.PAN_TILT_UNITS_PER_SPEED_STEP


def test_speed_zero_is_the_slowest_motion_not_a_stop():
    # Pelco manual 3.1.2: 0x00 is a valid but slow speed; stopping needs cleared bits.
    pelco, _ = make()
    run(pelco, make_frame(1, 0x00, PAN_RIGHT, 0x00, 0x00))
    assert pelco.state.pan_velocity == 1 * st.PAN_TILT_UNITS_PER_SPEED_STEP


def test_cleared_direction_bits_stop_their_axis():
    pelco, _ = make()
    run(pelco, make_frame(1, 0x00, PAN_RIGHT | ZOOM_TELE, 0x20, 0x00))
    assert pelco.state.pan_velocity > 0.0 and pelco.state.zoom_velocity > 0.0
    # a zoom-only frame stops the pan: the frame describes the whole motion state
    run(pelco, make_frame(1, 0x00, ZOOM_TELE, 0x3F, 0x00))
    assert pelco.state.pan_velocity == 0.0
    assert pelco.state.zoom_velocity > 0.0
    # ... and a pan-only frame stops the zoom
    run(pelco, make_frame(1, 0x00, PAN_RIGHT, 0x20, 0x00))
    assert pelco.state.zoom_velocity == 0.0
    assert pelco.state.pan_velocity > 0.0


def test_stop_all():
    pelco, camera = make()
    run(pelco, make_frame(1, 0x00, PAN_RIGHT, 0x20, 0x00))
    run(pelco, make_frame(1, 0x00, ZOOM_TELE, 0x3F, 0x00))
    frame = make_frame(1, 0x00, 0x00, 0x00, 0x00)
    assert run(pelco, frame) == [pelco.ack(frame)]
    assert not pelco.state.moving
    assert camera.log[-1].description == "stop all"


def test_zoom_tele_and_wide():
    pelco, _ = make()
    run(pelco, make_frame(1, 0x00, ZOOM_TELE, 0x3F, 0x00))
    assert pelco.state.zoom_velocity > 0.0
    run(pelco, make_frame(1, 0x00, ZOOM_WIDE, 0x3F, 0x00))
    assert pelco.state.zoom_velocity < 0.0


def test_focus_is_ignored_while_autofocus_is_on():
    pelco, camera = make()
    assert pelco.state.autofocus
    frame = make_frame(1, 0x00, FOCUS_FAR, 0x00, 0x00)
    assert run(pelco, frame) == [pelco.ack(frame)]  # the command is acked ...
    assert pelco.state.focus_velocity == 0.0  # ... but focus does not move
    assert any("autofocus" in e.description and not e.ok for e in camera.log)


def test_focus_far_in_cmd2_and_focus_near_in_cmd1_bit0():
    pelco, _ = make()
    pelco.state.autofocus = False
    run(pelco, make_frame(1, 0x00, FOCUS_FAR, 0x00, 0x00))  # FF 01 00 80 00 00 81
    assert pelco.state.focus_velocity < 0.0
    run(pelco, make_frame(1, 0x01, 0x00, 0x00, 0x00))  # FF 01 01 00 00 00 02
    assert pelco.state.focus_velocity > 0.0


def test_commands_are_ignored_in_standby():
    pelco, camera = make()
    pelco.state.power = False
    assert run(pelco, make_frame(1, 0x00, PAN_RIGHT, 0x20, 0x00)) == []
    assert pelco.state.pan_velocity == 0.0
    assert not camera.log[-1].ok


# ------------------------------------------------------------------- presets
def test_preset_set_call_clear():
    pelco, camera = make()
    pelco.state.pan, pelco.state.tilt = 100.0, -50.0
    # extended command: opcode in cmd2, preset number in data2
    assert run(pelco, make_frame(1, 0x00, 0x03, 0x00, 0x05)) == [bytes.fromhex("FF 01 00 09")]
    pelco.state.pan = pelco.state.tilt = 0.0
    assert run(pelco, make_frame(1, 0x00, 0x07, 0x00, 0x05)) == [bytes.fromhex("FF 01 00 0D")]
    # instant mode (the test camera has instant=True): the recall jumps at once
    assert (pelco.state.pan, pelco.state.tilt) == (100.0, -50.0)
    assert not pelco.state.busy
    assert run(pelco, make_frame(1, 0x00, 0x05, 0x00, 0x05)) == [bytes.fromhex("FF 01 00 0B")]
    assert 5 not in pelco.state.presets


def test_preset_frames_do_not_trigger_motion():
    pelco, _ = make()
    run(pelco, make_frame(1, 0x00, 0x03, 0x00, 0x05))  # set preset 5: cmd2 0x03 has bit 1 set
    assert not pelco.state.moving


def test_preset_recall_without_instant_mode_moves_at_motor_speed():
    camera = ViscaCamera(instant=False)
    pelco = PelcoCamera(camera)
    pelco.state.pan = 500.0
    run(pelco, make_frame(1, 0x00, 0x03, 0x00, 0x02))  # set preset 2
    pelco.state.pan = 0.0
    run(pelco, make_frame(1, 0x00, 0x07, 0x00, 0x02))  # call preset 2
    assert pelco.state.busy  # still moving towards the target, not jumped
    assert pelco.state.pan == 0.0


def test_call_of_an_unset_preset_gets_no_reply():
    pelco, camera = make()
    assert run(pelco, make_frame(1, 0x00, 0x07, 0x00, 0x09)) == []
    assert "not set" in camera.log[-1].description


def test_preset_number_above_99_gets_no_reply():
    pelco, camera = make()
    assert run(pelco, make_frame(1, 0x00, 0x03, 0x00, 200)) == []
    assert "out of range" in camera.log[-1].description


def test_unsupported_extended_commands_get_no_reply():
    pelco, camera = make()
    assert run(pelco, make_frame(1, 0x00, 0x45, 0x00, 0x00)) == []  # cmd2 opcode unknown
    assert run(pelco, make_frame(1, 0x10, 0x00, 0x00, 0x00)) == []  # cmd1 autoscan
    assert camera.log[-2].ok is False and camera.log[-1].ok is False


# ------------------------------------------------------------ end to end pty
@pytest.mark.skipif(not hasattr(os, "openpty"), reason="pty needs POSIX")
def test_pelco_d_over_pty(tmp_path):
    link = tmp_path / "ttyPelcoD"

    async def run():
        async with serve("--pelco-d", str(link), "--pelco-d-address", "7") as ctx:
            assert [str(e) for e in ctx.endpoints] == [f"Pelco-D serial {link}"]
            fd = os.open(str(link), os.O_RDWR | os.O_NOCTTY)
            try:
                os.write(fd, make_frame(7, 0x00, PAN_RIGHT, 0x20, 0x00))  # ... 29
                data = b""
                for _ in range(50):
                    await asyncio.sleep(0.02)
                    os.set_blocking(fd, False)
                    try:
                        data += os.read(fd, 64)
                    except BlockingIOError:
                        pass
                    if len(data) >= 4:
                        break
                return ctx, data
            finally:
                os.close(fd)

    ctx, data = asyncio.run(run())
    assert data == bytes([0xFF, 7, 0x00, 0x29])  # 4-byte general response
    assert ctx.state.pan_velocity > 0.0


@pytest.mark.skipif(not hasattr(os, "openpty"), reason="pty needs POSIX")
def test_pelco_d_plugin_releases_the_pty(tmp_path):
    link = tmp_path / "ttyPelcoD"

    async def run():
        async with serve("--pelco-d", str(link)) as ctx:
            port = ctx.plugins[0].servers[0]
            assert link.is_symlink()
            return port

    port = asyncio.run(run())
    assert (port.master, port.slave) == (-1, -1)
    assert not link.exists()
