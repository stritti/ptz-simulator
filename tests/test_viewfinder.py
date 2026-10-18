from ptzsim import state as st
from ptzsim.state import CameraState
from ptzsim.tui import DASHBOARD_WIDTH, TuiController
from ptzsim.viewfinder import CROSS, HORIZON, POST, framed_view, render_view
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


def test_standby_shows_no_picture():
    lines = view(power=False)
    assert any("STANDBY" in line for line in lines)
    assert not any(HORIZON in line for line in lines)


def test_framed_view_caption_and_size():
    s = CameraState(pan=30 * st.UNITS_PER_DEGREE)
    lines = framed_view(s, 40, 12)
    assert len(lines) == 12 and all(len(line) == 40 for line in lines)
    assert "+30.0°" in lines[0] and "1.0x" in lines[0]


def test_layout_side_by_side_and_stacked():
    tui = TuiController(ViscaCamera())
    lines, box = tui.layout("t", 160, 50)
    row, col, rows, cols = box
    assert col == DASHBOARD_WIDTH + 2 and lines[0][col] == "┌"
    lines, box = tui.layout("t", 80, 50)
    assert box[:2] == (0, 0) and lines[0].startswith("┌")
    assert any(line.startswith("PTZ camera simulator") for line in lines)
    lines, box = tui.layout("t", 20, 10)
    assert box is None
