# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

from ptzsim import state as st
from ptzsim.state import CameraState
from ptzsim.tui import DASHBOARD_WIDTH, TuiController
from ptzsim.viewfinder import CROSS, HORIZON, POST, framed_view, render_picture, render_view
from ptzsim.visca import ViscaCamera

COLS, ROWS = 59, 15


def view(pan_deg=0.0, tilt_deg=0.0, zoom=0.0, **kwargs):
    s = CameraState(pan=pan_deg * st.UNITS_PER_DEGREE, tilt=tilt_deg * st.UNITS_PER_DEGREE,
                    zoom=zoom, **kwargs)
    return render_view(s, COLS, ROWS)


def test_home_position_shows_horizon_post_and_label():
    lines = view()
    assert len(lines) == ROWS and all(len(line) == COLS for line in lines)
    centre = lines[ROWS // 2]
    assert centre[COLS // 2] == CROSS
    assert set(centre.replace(CROSS, "")) == {HORIZON}  # horizon through the crosshair
    assert sum(line.count(HORIZON * 3) > 0 for line in lines) == 1  # drawn exactly once
    assert lines[ROWS // 2 + 1][COLS // 2] == POST  # the 0° post below the crosshair
    assert any("0°" in line for line in lines[: ROWS // 2])


def test_pan_moves_the_scene():
    right = "".join(view(pan_deg=45))
    left = "".join(view(pan_deg=-45))
    assert " 45°" in right and "-45°" not in right
    assert "-45°" in left and " 45°" not in left


def test_tilt_moves_the_horizon():
    up = view(tilt_deg=10)
    down = view(tilt_deg=-10)
    row_up = next(i for i, line in enumerate(up) if HORIZON * 3 in line)
    row_down = next(i for i, line in enumerate(down) if HORIZON * 3 in line)
    assert row_up > ROWS // 2 > row_down


def test_zoom_narrows_the_field_of_view():
    wide = view(pan_deg=20)
    tele = view(pan_deg=20, zoom=st.ZOOM_MAX)
    assert sum(line.count(POST) for line in wide) > 0
    assert sum(line.count(POST) for line in tele) == 0  # nearest post is 25° away


def test_standby_dims_the_picture():
    s = CameraState(power=False)
    lines, styles = render_picture(s, COLS, ROWS)
    assert any("STANDBY" in line for line in lines)
    assert any(HORIZON in line for line in lines)  # the camera still points somewhere
    assert {style for row in styles for style in row} <= {"dim", "bold"}


def test_framed_view_caption_and_size():
    s = CameraState(pan=30 * st.UNITS_PER_DEGREE)
    lines = framed_view(s, 40, 12)
    assert len(lines) == 12 and all(len(line) == 40 for line in lines)
    assert "+30.0°" in lines[0] and "1.0x" in lines[0]


def test_layout_side_by_side_and_minimum_width():
    tui = TuiController(ViscaCamera())
    for width in (120, 160):
        lines, box = tui.layout("t", width, 50)
        row, col, rows, cols = box
        assert row == 2 and col == DASHBOARD_WIDTH + 2 and lines[row][col] == "┌"
        assert "Camera" in lines[0]
    lines, box = tui.layout("t", 79, 50)
    assert box is None
    assert any("80 columns" in line for line in lines)


def tab(tui, lines):
    """The highlighted header tab."""
    return next(lines[row][col:col + length] for row, col, length, style in tui.spans
                if style == "accent")


def test_network_view_uses_full_dashboard_without_camera_picture():
    tui = TuiController(ViscaCamera())
    for width, height in ((160, 50), (120, 50)):
        tui.handle_key("n")
        lines, box = tui.layout("t", width, height)
        assert "[n] Network" in tab(tui, lines)
        assert box is None
        tui.handle_key("c")
        lines, box = tui.layout("t", width, height)
        assert "[c] Camera" in tab(tui, lines)
        assert box is not None
