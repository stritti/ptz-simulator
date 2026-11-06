# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Unit tests for the camera model (ptzsim.state.CameraState)."""

import pytest

from ptzsim import state as st
from ptzsim.state import CameraState, clamp


def test_clamp():
    assert clamp(5, 0, 10) == 5
    assert clamp(-1, 0, 10) == 0
    assert clamp(11, 0, 10) == 10


def test_position_and_derived_properties():
    s = CameraState()
    s.pan = 10 * st.UNITS_PER_DEGREE
    s.tilt = -5 * st.UNITS_PER_DEGREE
    assert s.pan_degrees == pytest.approx(10)
    assert s.tilt_degrees == pytest.approx(-5)
    assert s.position() == (round(s.pan), round(s.tilt), round(s.zoom), round(s.focus))
    assert s.zoom_ratio == pytest.approx(1.0)
    s.zoom = st.ZOOM_MAX
    assert s.zoom_ratio == pytest.approx(st.MAX_OPTICAL_ZOOM)


def test_busy_moving_and_axes_busy():
    s = CameraState()
    assert not s.busy and not s.moving
    s.move_pan_tilt_to(100, 0, 1, 1)
    assert s.busy and s.moving
    assert s.axes_busy(("pan", "tilt")) and not s.axes_busy(("zoom", "focus"))
    s.stop_pan_tilt()
    assert not s.busy and not s.moving
    s.drive_zoom(1, 1)
    assert s.moving and not s.busy


def test_drive_pan_tilt_clears_targets_and_sets_velocities():
    s = CameraState()
    s.move_pan_tilt_to(100, 100, 1, 1)
    s.drive_pan_tilt(1, -1, 2, 3)
    assert s.pan_target is None and s.tilt_target is None
    assert s.pan_velocity == 2 * st.PAN_TILT_UNITS_PER_SPEED_STEP
    assert s.tilt_velocity == -3 * st.PAN_TILT_UNITS_PER_SPEED_STEP


def test_move_pan_tilt_to_clamps_to_limits():
    s = CameraState()
    s.move_pan_tilt_to(10 ** 9, -10 ** 9, 1, 1)
    assert s.pan_target[0] == st.PAN_MAX
    assert s.tilt_target[0] == st.TILT_MIN


def test_home_and_set_home():
    s = CameraState()
    s.pan, s.tilt = 500, -100
    s.set_home()
    assert s.home_position == (500, -100)
    s.pan = s.tilt = 0
    s.home()
    assert s.pan_target[0] == 500 and s.tilt_target[0] == -100


def test_gains_are_clamped_and_one_push_resets():
    s = CameraState()
    s.set_white_balance("indoor")
    assert s.white_balance == "indoor"
    s.set_gains(1000, -5)
    assert (s.red_gain, s.blue_gain) == (st.WB_GAIN_MAX, 0)
    s.one_push_white_balance()
    assert s.white_balance == "manual"
    assert (s.red_gain, s.blue_gain) == (st.WB_GAIN_NEUTRAL, st.WB_GAIN_NEUTRAL)


def test_zoom_and_focus_drive_and_absolute():
    s = CameraState()
    s.drive_zoom(1, 7)
    assert s.zoom_target is None
    assert s.zoom_velocity == 8 * st.ZOOM_UNITS_PER_SPEED_STEP
    s.zoom_to(st.ZOOM_MAX + 100)  # clamped to the limit
    assert s.zoom_target[0] == st.ZOOM_MAX
    assert s.zoom_velocity == 0
    s.drive_focus(-1, 0)
    assert s.focus_velocity == -1 * st.FOCUS_UNITS_PER_SPEED_STEP
    s.focus_to(st.FOCUS_MIN - 100)  # clamped to the limit
    assert s.focus_target[0] == st.FOCUS_MIN


def test_presets_save_keeps_name_recall_and_clear():
    s = CameraState()
    s.pan, s.tilt, s.zoom, s.focus = 10, 20, 0x100, 0x2000
    s.save_preset(3, name="gate")
    s.pan = 0
    s.save_preset(3)  # saving again without a name keeps the old one
    assert s.presets[3].name == "gate"
    assert s.presets[3].pan == 0  # new position stored
    assert s.recall_preset(3)
    assert s.last_preset == 3
    assert s.pan_target[0] == 0 and s.zoom_target[0] == 0x100
    s.clear_preset(3)
    assert 3 not in s.presets
    assert not s.recall_preset(3)


def test_recall_preset_moves_focus_only_in_manual_focus():
    s = CameraState()
    s.save_preset(1)
    assert s.recall_preset(1)
    assert s.focus_target is None  # autofocus: focus is not driven
    s2 = CameraState()
    s2.autofocus = False
    s2.save_preset(1)
    assert s2.recall_preset(1)
    assert s2.focus_target is not None


def test_recall_speed_from_speed_settings():
    s = CameraState()
    assert s.recall_speed(0) == 1.0  # default: maximum
    s.preset_speed_mode = "common"
    s.common_preset_speed = 25
    assert s.recall_speed(0) == 0.5
    s.preset_speed_mode = "separate"
    s.preset_speeds[2] = 10
    assert s.recall_speed(2) == pytest.approx(10 / st.PRESET_SPEED_MAX)
    assert s.recall_speed(3) == 1.0


def test_recall_preset_clamps_speed():
    s = CameraState()
    s.save_preset(0)
    assert s.recall_preset(0, speed=0.0)  # clamped to the minimum 0.05
    assert s.pan_target[1] == pytest.approx(0.05 * st.PAN_SPEED_MAX * st.PAN_TILT_UNITS_PER_SPEED_STEP)


def test_free_preset_number():
    s = CameraState()
    assert s.free_preset_number() == 0
    for n in range(st.PRESET_COUNT):
        s.save_preset(n)
    assert s.free_preset_number() is None


def test_stop_axes_and_stop_all():
    s = CameraState()
    s.move_pan_tilt_to(100, 100, 1, 1)
    s.zoom_to(100)
    s.focus_to(0x4000)
    s.drive_zoom(1, 1)
    s.stop_axes(("pan", "zoom"))
    assert s.pan_target is None and s.zoom_target is None
    assert s.tilt_target is not None and s.focus_target is not None
    assert s.zoom_velocity != 0  # continuous motion is not touched by stop_axes
    s.stop_all()
    assert not s.moving and not s.busy
    s.stop_absolute()
    assert not s.busy


def test_finish_moves_jumps_to_all_targets():
    s = CameraState()
    s.move_pan_tilt_to(100, -50, 1, 1)
    s.zoom_to(0x2000)
    s.focus_to(0x4000)
    s.finish_moves()
    assert s.position() == (100, -50, 0x2000, 0x4000)
    assert not s.busy


def test_tick_velocity_stops_at_the_limit():
    s = CameraState()
    s.drive_pan_tilt(1, 0, st.PAN_SPEED_MAX, 1)
    s.tick(1000)
    assert s.pan == st.PAN_MAX
    assert s.pan_velocity == 0


def test_tick_approaches_target_and_completes():
    s = CameraState()
    s.move_pan_tilt_to(100, 0, 1, 1)
    s.tick(0.001)
    assert 0 < s.pan < 100
    assert s.pan_target is not None
    s.tick(100)
    assert s.pan == 100
    assert s.pan_target is None
