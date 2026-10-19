from ptzsim import state as st
from ptzsim.tui import JOG_TIMEOUT, SPEED_LEVELS, TuiController
from ptzsim.visca import ViscaCamera


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def make(instant=False):
    clock = Clock()
    return TuiController(ViscaCamera(instant=instant), clock=clock), clock


def test_arrow_starts_jog_and_stops_after_key_repeat_ends():
    tui, clock = make()
    tui.handle_key("RIGHT")
    assert tui.state.pan_velocity > 0
    clock.now += JOG_TIMEOUT / 2
    tui.handle_key("RIGHT")  # key repeat keeps the jog alive
    clock.now += JOG_TIMEOUT / 2
    tui.tick()
    assert tui.state.pan_velocity > 0
    clock.now += JOG_TIMEOUT
    tui.tick()
    assert tui.state.pan_velocity == 0


def test_key_repeat_logs_one_entry():
    tui, _ = make()
    for _ in range(5):
        tui.handle_key("UP")
    entries = [e for e in tui.camera.log if e.source == "TUI"]
    assert [e.description for e in entries] == [f"pan/tilt up (speed {SPEED_LEVELS // 2})"]
    assert tui.state.tilt_velocity > 0


def test_speed_keys_change_jog_speed():
    tui, _ = make()
    tui.handle_key("]")
    tui.handle_key("d")
    fast = tui.state.pan_velocity
    tui.handle_key(" ")
    for _ in range(SPEED_LEVELS):
        tui.handle_key("[")
    assert tui.speed == 1
    tui.handle_key("d")
    assert 0 < tui.state.pan_velocity < fast


def test_zoom_jog_and_stop():
    tui, clock = make()
    tui.handle_key("+")
    assert tui.state.zoom_velocity > 0
    tui.handle_key("-")
    assert tui.state.zoom_velocity < 0
    tui.handle_key(" ")
    assert not tui.state.moving


def test_b_key_one_push_white_balance():
    tui, _ = make()
    tui.state.red_gain, tui.state.blue_gain = 0x40, 0xC0
    tui.handle_key("b")
    assert tui.state.white_balance == "manual" and (tui.state.red_gain, tui.state.blue_gain) == (0x80, 0x80)
    assert tui.camera.log[-1].description == "one push white balance"


def test_save_recall_and_clear_preset():
    tui, _ = make(instant=True)
    tui.state.pan, tui.state.tilt, tui.state.zoom = 500, 200, 0x2000
    tui.handle_key("P")
    tui.handle_key("3")
    assert 2 in tui.state.presets
    tui.handle_key("h")
    assert (tui.state.pan, tui.state.tilt) == (0, 0)
    tui.handle_key("3")
    assert tui.state.position()[:3] == (500, 200, 0x2000)
    tui.handle_key("C")
    tui.handle_key("3")
    assert 2 not in tui.state.presets
    tui.handle_key("3")
    assert tui.message == "preset 3 is empty"


def test_standby_blocks_moves():
    tui, _ = make()
    tui.handle_key("o")
    assert not tui.state.power
    tui.handle_key("LEFT")
    assert tui.state.pan_velocity == 0
    assert "standby" in tui.message


def test_quit_and_frame():
    tui, _ = make()
    lines = tui.frame("test")
    assert lines[0].startswith("PTZ camera simulator")
    assert any("q quit" in line for line in lines)
    assert not any(line.startswith("Ctrl+C") for line in lines)
    tui.handle_key("q")
    assert tui.quit


def test_position_limits_still_apply():
    tui, clock = make()
    tui.handle_key("LEFT")
    tui.state.tick(60)
    assert tui.state.pan == st.PAN_MIN
