# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

import asyncio
from contextlib import suppress
import os
from pathlib import Path
import re
import select
import signal
import struct
import subprocess
import sys
import time

import pytest

from ptzsim import display, state as st
from ptzsim.tui import JOG_TIMEOUT, SPEED_LEVELS, TuiController, _draw
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
    tui.handle_key("n")
    tui.handle_key("c")
    assert 2 in tui.state.presets
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
    screen, _ = tui.layout("test", 120, 24)
    assert "[q]" in screen[-1] and "Quit" in screen[-1]
    assert not any(line.startswith("Ctrl+C") for line in lines)
    tui.handle_key("q")
    assert tui.quit


def test_network_and_camera_keys_switch_rendered_view():
    tui, _ = make()
    for key in ("n", "n"):
        tui.handle_key(key)
        lines = tui.frame("test")
        assert lines[0].startswith("Network Information")
        assert any(line.startswith("Hostname: ") for line in lines)
        assert any(line.startswith("FQDN: ") for line in lines)
        screen, _ = tui.layout("test", 120, 24)
        assert "[n]:Network" in screen[1]

    tui.handle_key("C")
    assert tui.pending == "clear"
    assert tui.frame("test")[0].startswith("Network Information")
    for key in ("c", "c"):
        tui.handle_key(key)
        lines = tui.frame("test")
        assert lines[0].startswith("PTZ camera simulator")
        screen, _ = tui.layout("test", 120, 24)
        assert "[c]:Camera" in screen[1]
        assert tui.pending is None


def test_serve_switches_views_in_a_terminal(tmp_path):
    pty = pytest.importorskip("pty")
    fcntl = pytest.importorskip("fcntl")
    termios = pytest.importorskip("termios")
    pytest.importorskip("curses")
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 160, 0, 0))
    env = dict(os.environ, TERM="xterm-256color",
               PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    process = subprocess.Popen(
        [sys.executable, "-m", "ptzsim", "serve", "--host", "127.0.0.1",
         "--onvif", "0", "--no-discovery"],
        stdin=slave, stdout=slave, stderr=slave, cwd=tmp_path, env=env,
    )

    def expect_output(text, timeout=5):
        output = bytearray()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], max(0, deadline - time.monotonic()))
            if ready:
                output.extend(os.read(master, 65536))
                if text.encode() in output:
                    return
        pytest.fail(f"Terminal did not show {text!r}; last output: {bytes(output[-500:])!r}")

    try:
        expect_output("PTZ camera simulator")
        os.write(master, b"f")
        expect_output("autofocus off")
        os.write(master, b"n")
        expect_output("Network Information")
        os.write(master, b"c")
        expect_output("PTZ camera simulator")
        os.write(master, b"P")
        expect_output("save preset: press 1-9")
        os.write(master, b"\x1b")
        expect_output("preset action cancelled", timeout=0.5)
        os.write(master, b"?")
        expect_output("Keyboard commands")
        os.write(master, b"c")
        expect_output("PTZ camera simulator")
        os.write(master, b"P")
        expect_output("save preset: press 1-9")
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 119, 0, 0))
        os.kill(process.pid, signal.SIGWINCH)
        expect_output("Minimum: 120 columns")
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 120, 0, 0))
        os.kill(process.pid, signal.SIGWINCH)
        expect_output("save preset: press 1-9")
        os.write(master, b"3")
        expect_output("save preset 3")
        os.write(master, b"q")
        assert process.wait(timeout=5) == 0
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        os.close(master)
        os.close(slave)


def test_position_limits_still_apply():
    tui, clock = make()
    tui.handle_key("LEFT")
    tui.state.tick(60)
    assert tui.state.pan == st.PAN_MIN


@pytest.mark.parametrize("width,height", [
    (160, 40), (120, 24), (120, 17), (120, 16), (120, 15), (120, 14), (120, 8),
])
@pytest.mark.parametrize("view", ["camera", "network"])
def test_layout_keeps_view_and_commands_visible_with_overflow(width, height, view):
    tui, _ = make()
    for number in range(9):
        tui.state.save_preset(number)
    for number in range(30):
        tui.camera.record("test", f"command {number}")
    tui.handle_key("n" if view == "network" else "c")
    lines, box = tui.layout("test", width, height)
    assert len(lines) == height
    assert all(len(line) <= width for line in lines)
    assert view.upper() in lines[0]
    assert "[q]" in lines[-1] and "Quit" in lines[-1]
    assert "[?]" in "\n".join(lines[-2:])
    assert "Space" in "\n".join(lines[-12:])
    if box:
        top, left, rows, cols = box
        assert top >= 2
        assert top + rows <= height - len(tui.shortcuts(width, height)) - 1
        assert left + cols <= width


def test_paging_reaches_hidden_content_without_moving_camera():
    tui, _ = make()
    for number in range(9):
        tui.state.save_preset(number)
    before, _ = tui.layout("test", 120, 24)
    tui.handle_key("PAGEDOWN")
    lines, _ = tui.layout("test", 120, 24)
    assert lines[2:-4] != before[2:-4]
    assert any("Last commands" in line for line in lines)
    assert not tui.state.moving
    tui.handle_key("PAGEUP")
    lines, _ = tui.layout("test", 120, 24)
    assert any("Power:" in line for line in lines)


def test_compact_help_can_be_paged_and_closed_without_losing_view():
    tui, _ = make()
    tui.handle_key("n")
    tui.handle_key("?")
    lines, box = tui.layout("test", 120, 12)
    assert "HELP" in lines[0] and "NETWORK" in lines[0]
    assert box is None
    seen = "\n".join(lines)
    for _ in range(12):
        tui.handle_key("PAGEDOWN")
        lines, _ = tui.layout("test", 120, 12)
        seen += "\n".join(lines)
    for command in ("autofocus", "white balance", "standby", "preset"):
        assert command in seen
    tui.handle_key("ESC")
    lines, _ = tui.layout("test", 120, 12)
    assert "NETWORK" in lines[0] and "HELP" not in lines[0]
    assert tui.current_view == "network"


def test_pending_preset_prompt_survives_overflow_and_escape_cancels():
    tui, _ = make()
    for number in range(9):
        tui.state.save_preset(number)
    tui.handle_key("P")
    lines, _ = tui.layout("test", 120, 24)
    status_row = len(lines) - len(tui.shortcuts(120, 24)) - 1
    assert "save preset: press 1-9" in lines[status_row]
    tui.handle_key("ESC")
    assert tui.pending is None
    assert "cancel" in tui.message


def test_help_cancels_pending_preset_and_keeps_emergency_stop_available():
    tui, _ = make()
    tui.handle_key("RIGHT")
    tui.handle_key("P")
    tui.handle_key("?")
    lines, _ = tui.layout("test", 120, 24)
    assert lines[0].startswith("HELP")
    assert tui.pending is None
    tui.handle_key("3")
    assert not tui.state.presets
    tui.handle_key(" ")
    assert not tui.state.moving
    tui.handle_key("n")
    lines, _ = tui.layout("test", 120, 24)
    assert lines[0].startswith("NETWORK")


def test_compact_status_keeps_scroll_range_visible_after_long_feedback():
    tui, _ = make()
    tui.handle_key("RIGHT")
    tui.message = "status " * 25
    lines, _ = tui.layout("test", 120, 10)
    assert any(re.search(r"\d+-\d+/\d+$", line) for line in lines[-4:])


def test_compact_status_does_not_repeat_the_separator_when_truncated():
    tui, _ = make()
    tui.message = "x" * 109 + " | pending"
    lines, _ = tui.layout("test", 120, 10)
    status = next(line for line in lines[-4:] if re.search(r"\d+-\d+/\d+$", line))
    assert "| |" not in status


@pytest.mark.parametrize("width,height", [(160, 40), (120, 24), (120, 17), (120, 15)])
@pytest.mark.parametrize("view_key", ["c", "n"])
def test_footer_groups_and_labels_all_available_commands(width, height, view_key):
    tui, _ = make()
    tui.handle_key(view_key)
    lines, _ = tui.layout("test", width, height)
    footer = lines[-4:]
    groups = [
        ("MOVE", (("[Arrows/WASD]", "Pan/Tilt"), ("[+/-]", "Zoom"),
                  ("[Space]", "Stop"), ("[ / ]", "Speed"), ("[h]", "Home"))),
        ("PRESET", (("[1-9]", "Recall"), ("[P then 1-9]", "Save"),
                    ("[C then 1-9]", "Clear"))),
        ("CAMERA", (("[f]", "Autofocus"), ("[b]", "White balance"), ("[o]", "Power"))),
        ("VIEW", (("[c]", "Camera"), ("[n]", "Network"), ("[PgUp/PgDn]", "Scroll"),
                  ("[?]", "Help"), ("[q]", "Quit"))),
    ]
    for index, (group, commands) in enumerate(groups):
        start = footer[0].index(group)
        end = footer[0].index(groups[index + 1][0]) if index + 1 < len(groups) else width
        column = [line[start:end] for line in footer]
        for key, action in commands:
            assert any(re.search(re.escape(key) + r"\s+" + re.escape(action), line)
                       for line in column)
    assert "[?]" in "\n".join(lines[-2:])
    assert "[q]" in lines[-1] and "Quit" in lines[-1]


@pytest.mark.parametrize("width,height", [
    (120, 8), (120, 10), (120, 12), (120, 14), (160, 14),
])
def test_compact_footer_keeps_essential_actions_separate_and_readable(width, height):
    tui, _ = make()
    lines, _ = tui.layout("test", width, height)
    footer = "\n".join(lines[-4:])
    assert "[Space] Stop" in footer
    assert "PgUp" in footer and "Scroll" in footer
    assert "[?]" in lines[-1] and "Help" in lines[-1]
    assert "[q]" in lines[-1] and "Quit" in lines[-1]
    assert all(len(line) <= width for line in lines)


def test_help_footer_describes_only_available_actions():
    tui, _ = make()
    tui.handle_key("?")
    lines, _ = tui.layout("test", 120, 24)
    footer = "\n".join(lines[-2:])
    assert "[Space]" in footer and "Stop" in footer
    assert "[PgUp/PgDn]" in footer and "Scroll" in footer
    assert "[?/Esc]" in footer and "Back" in footer
    assert "[q]" in footer and "Quit" in footer
    assert "Pan/Tilt" not in footer


@pytest.mark.parametrize("use_color", [True, False])
def test_footer_keys_are_visually_distinct_from_actions(use_color):
    curses = pytest.importorskip("curses")
    tui, _ = make()
    lines, _ = tui.layout("test", 120, 24)

    class Screen:
        def __init__(self):
            self.cells = [[None] * 120 for _ in range(24)]

        def getmaxyx(self):
            return 24, 120

        def erase(self):
            pass

        def addnstr(self, row, col, text, count, attr):
            for offset, char in enumerate(text[:count]):
                if col + offset < 120:
                    self.cells[row][col + offset] = (char, attr)

        def refresh(self):
            pass

    screen = Screen()
    colors = {"header": 1, "commands": 2, "shortcut": 3, "status": 4} if use_color else {}
    _draw(screen, lines, None, colors, footer_rows=len(tui.shortcuts(120, 24)) + 1)
    column = lines[-1].index("[q]")
    key = screen.cells[-1][column]
    action = screen.cells[-1][lines[-1].index("Quit")]
    assert key[0] == "[" and action[0] == "Q"
    if use_color:
        assert key[1] & ~curses.A_BOLD == colors["shortcut"]
        assert action[1] == colors["commands"]
    else:
        assert key[1] == curses.A_BOLD
        assert action[1] == curses.A_REVERSE


@pytest.mark.parametrize("view_key,view_name", [("c", "CAMERA"), ("n", "NETWORK")])
def test_terminal_width_requires_120_columns_and_recovers_on_resize(view_key, view_name):
    tui, _ = make()
    tui.handle_key(view_key)
    lines, box = tui.layout("test", 119, 24)
    assert lines[0].startswith(view_name)
    assert any("120 columns" in line for line in lines)
    assert "[Space]" in lines[-1] and "[q]" in lines[-1]
    assert box is None

    lines, _ = tui.layout("test", 120, 24)
    assert lines[0].startswith(view_name)
    assert any(line.startswith("MOVE") for line in lines)
    assert not any("Terminal too small" in line for line in lines)


@pytest.mark.parametrize("width", [20, 80, 119])
def test_resize_notice_keeps_stop_and_quit_available(width):
    tui, _ = make()
    lines, box = tui.layout("test", width, 10)
    assert len(lines) == 10 and box is None
    assert any("120 columns" in line for line in lines)
    assert "[Space]" in "\n".join(lines[-2:])
    assert "[q]" in lines[-1]
    tui.handle_key("RIGHT")
    tui.handle_key(" ")
    assert not tui.state.moving
    tui.handle_key("q")
    assert tui.quit


def test_resize_notice_preserves_open_help():
    tui, _ = make()
    tui.handle_key("n")
    tui.handle_key("?")
    lines, _ = tui.layout("test", 119, 24)
    assert lines[0].startswith("HELP | NETWORK")
    lines, _ = tui.layout("test", 120, 24)
    assert lines[0].startswith("HELP | NETWORK")
    assert any("Keyboard commands" in line for line in lines)


@pytest.mark.parametrize("width", [120, 160])
def test_footer_uses_four_aligned_columns_in_four_rows(width):
    tui, _ = make()
    lines = tui.shortcuts(width, 24)
    assert len(lines) == 4
    for group, key in (("MOVE", "[Arrows/WASD]"), ("PRESET", "[1-9]"),
                       ("CAMERA", "[f]"), ("VIEW", "[c]")):
        assert lines[0].index(group) == lines[1].index(key)
    for group in ("PRESET", "CAMERA", "VIEW"):
        start = lines[0].index(group)
        assert all(line[start - 6:start] == " " * 6 for line in lines)
    assert lines[1].index("Pan/Tilt") == lines[2].index("Zoom") == lines[3].index("Stop")
    assert lines[2].index("[h]") == lines[3].index("[ / ]")
    assert lines[2].index("[?]") == lines[3].index("[q]")
    assert all(len(line) <= width for line in lines)


@pytest.mark.parametrize("width", [120, 160, 240])
def test_footer_commands_stay_compact_on_wide_terminals(width):
    tui, _ = make()
    lines = tui.shortcuts(width, 24)
    assert max(map(len, lines)) <= 120


def test_shorter_footer_leaves_more_room_for_content():
    tui, _ = make()
    for number in range(9):
        tui.state.save_preset(number)
    lines, _ = tui.layout("test", 120, 24)
    assert re.search(r"1-17/\d+$", lines[-5])


def test_resize_preserves_pending_preset_and_current_view():
    tui, _ = make()
    tui.handle_key("n")
    tui.handle_key("P")
    tui.handle_key("KEY_RESIZE")
    tui.layout("test", 119, 24)
    lines, _ = tui.layout("test", 120, 24)
    assert tui.pending == "save"
    assert tui.current_view == "network"
    assert any("save preset: press 1-9" in line for line in lines)


def test_cli_help_without_unix_terminal_modules(tmp_path):
    script = """\
import builtins
original_import = builtins.__import__
def import_without_terminal_modules(name, *args, **kwargs):
    if name in ("termios", "tty", "fcntl"):
        raise ModuleNotFoundError(name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = import_without_terminal_modules
from ptzsim.cli import main
main(["serve", "--help"])
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert "--no-tui" in result.stdout


@pytest.mark.skipif(sys.platform == "win32", reason="select monitors Unix file descriptors")
def test_dashboard_input_eof_does_not_request_shutdown(monkeypatch):
    state = display.DashboardState()

    async def run():
        await asyncio.wait_for(
            display.read_keyboard_input(state, asyncio.get_running_loop()), timeout=2,
        )
        assert not state.should_quit

    with open(os.devnull) as stream:
        monkeypatch.setattr(sys, "stdin", stream)
        asyncio.run(run())


@pytest.mark.parametrize("check", ["output-processing", "cancellation"])
def test_dashboard_input_preserves_terminal_modes(monkeypatch, check):
    pty = pytest.importorskip("pty")
    termios = pytest.importorskip("termios")
    master, slave = pty.openpty()
    before = termios.tcgetattr(slave)
    state = display.DashboardState()

    async def run():
        task = asyncio.create_task(
            display.read_keyboard_input(state, asyncio.get_running_loop())
        )

        async def wait_until(predicate):
            deadline = time.monotonic() + 2
            while not predicate():
                if task.done():
                    task.result()
                assert time.monotonic() < deadline, "dashboard input did not become ready"
                await asyncio.sleep(0.01)

        try:
            await wait_until(lambda: not termios.tcgetattr(slave)[3] & termios.ICANON)
            os.write(master, b"n")
            await wait_until(lambda: state.current_view == "network")
            if check == "output-processing":
                assert termios.tcgetattr(slave)[1] & termios.OPOST == before[1] & termios.OPOST
            else:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert termios.tcgetattr(slave) == before
        finally:
            state.should_quit = True
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            deadline = time.monotonic() + 2
            while termios.tcgetattr(slave) != before and time.monotonic() < deadline:
                await asyncio.sleep(0.01)

    try:
        with os.fdopen(os.dup(slave)) as stream:
            monkeypatch.setattr(sys, "stdin", stream)
            asyncio.run(run())
    finally:
        os.close(master)
        os.close(slave)


# ------------------------------------------------------- missing key handling
def test_autofocus_key_toggles_autofocus():
    tui, _ = make()
    assert tui.state.autofocus
    tui.handle_key("f")
    assert not tui.state.autofocus
    assert tui.camera.log[-1].description == "autofocus off"
    tui.handle_key("f")
    assert tui.state.autofocus
    assert tui.camera.log[-1].description == "autofocus on"


def test_zoom_jog_stops_when_the_key_repeat_ends():
    tui, clock = make()
    tui.handle_key("+")
    assert tui.state.zoom_velocity > 0
    clock.now += JOG_TIMEOUT + 0.01
    tui.tick()
    assert tui.state.zoom_velocity == 0


def test_zoom_jog_is_blocked_in_standby():
    tui, _ = make()
    tui.handle_key("o")
    tui.handle_key("+")
    assert tui.state.zoom_velocity == 0
    assert "standby" in tui.message


def test_zoom_key_repeat_keeps_a_single_log_entry():
    tui, _ = make()
    tui.handle_key("+")
    tui.handle_key("+")
    tui.handle_key("=")
    entries = [e for e in tui.camera.log if e.source == "TUI"]
    assert [e.description for e in entries] == [f"zoom tele (speed {SPEED_LEVELS // 2})"]


def test_tiny_terminal_shows_a_single_resize_hint():
    tui, _ = make()
    lines, box = tui.layout("t", 100, 2)
    assert box is None
    assert lines[0] == "Resize: 120x8"
    assert "[q]" in lines[1]


# ------------------------------------------- curses helpers with a fake module
import types

from ptzsim import tui as tui_mod


class FakeScreen:
    def __init__(self, keys=(), size=(24, 120)):
        self.keys = list(keys)
        self.size = size
        self.calls = []
        self.error = None  # set by fake_curses()

    def keypad(self, on):
        self.calls.append(("keypad", on))

    def nodelay(self, on):
        self.calls.append(("nodelay", on))

    def getmaxyx(self):
        return self.size

    def erase(self):
        self.calls.append(("erase",))

    def addnstr(self, row, col, text, count, attr):
        self.calls.append(("addnstr", row, col, text[:count], attr))

    def addstr(self, row, col, ch, attr):
        self.calls.append(("addstr", row, col, ch, attr))

    def refresh(self):
        self.calls.append(("refresh",))

    def getkey(self):
        if self.keys:
            return self.keys.pop(0)
        raise self.error()


def fake_curses(keys=(), size=(24, 120), **overrides):
    mod = types.ModuleType("curses")

    class error(Exception):
        pass

    mod.error = error
    mod.A_NORMAL, mod.A_BOLD, mod.A_REVERSE = 0, 1, 2
    for index, name in enumerate(("BLACK", "RED", "GREEN", "YELLOW", "BLUE", "MAGENTA", "CYAN", "WHITE")):
        setattr(mod, "COLOR_" + name, index)
    screen = FakeScreen(keys, size)
    screen.error = error
    mod._screen = screen
    mod.initscr = lambda: screen
    mod.noecho = mod.cbreak = mod.nocbreak = mod.echo = mod.endwin = lambda: None
    mod.curs_set = lambda visibility: None
    mod.has_colors = lambda: True
    mod.start_color = lambda: None
    mod.use_default_colors = lambda: None
    mod.init_pair = lambda number, fg, bg: None
    mod.color_pair = lambda number: 1000 + number
    for key, value in overrides.items():
        setattr(mod, key, value)
    return mod


def test_interactive_processes_keys_until_quit(monkeypatch):
    monkeypatch.delenv("ESCDELAY", raising=False)  # interactive() only sets the default
    mod = fake_curses(keys=["d", "\x1b", "[", "C", "q"])
    monkeypatch.setitem(sys.modules, "curses", mod)
    cam = ViscaCamera()
    asyncio.run(tui_mod.interactive(cam, "title", interval=0.01))
    screen = mod._screen
    assert os.environ.get("ESCDELAY") == "100"
    assert any(call[0] == "refresh" for call in screen.calls)
    assert any(call[0] == "addnstr" for call in screen.calls)
    assert ("keypad", False) in screen.calls  # terminal restored on exit
    descriptions = [e.description for e in cam.log]
    assert any("pan/tilt right" in d for d in descriptions)  # "d" and ESC [ C both jog right


def test_interactive_tolerates_curs_set_failure(monkeypatch):
    mod = fake_curses(keys=["q"])

    def broken_curs_set(visibility):
        raise mod.error()

    mod.curs_set = broken_curs_set
    monkeypatch.setitem(sys.modules, "curses", mod)
    asyncio.run(tui_mod.interactive(ViscaCamera(), "t", interval=0.01))
    assert ("keypad", False) in mod._screen.calls


@pytest.mark.parametrize("keys, expected", [
    (["[", "A"], "UP"), (["[", "B"], "DOWN"), (["[", "C"], "RIGHT"), (["[", "D"], "LEFT"),
    (["O", "A"], "UP"), (["O", "B"], "DOWN"), (["[", "5", "~"], "PAGEUP"), (["[", "6", "~"], "PAGEDOWN"),
    (["x"], "ESC"), ([], "ESC"),
])
def test_escape_sequence_maps_raw_arrow_keys(monkeypatch, keys, expected):
    mod = fake_curses(keys=keys)
    monkeypatch.setitem(sys.modules, "curses", mod)
    assert tui_mod._escape_sequence(mod._screen) == expected


def test_init_colors_without_color_support(monkeypatch):
    mod = fake_curses(has_colors=lambda: False)
    monkeypatch.setitem(sys.modules, "curses", mod)
    assert tui_mod._init_colors() == {}


def test_init_colors_when_start_color_fails(monkeypatch):
    mod = fake_curses(start_color=lambda: (_ for _ in ()).throw(mod.error()))
    monkeypatch.setitem(sys.modules, "curses", mod)
    assert tui_mod._init_colors() == {}


def test_init_colors_registers_the_chrome_pairs(monkeypatch):
    mod = fake_curses()
    monkeypatch.setitem(sys.modules, "curses", mod)
    colors = tui_mod._init_colors()
    assert colors["header"] == 1001 and colors["commands"] == 1002
    assert colors["shortcut"] == 1003 and colors["status"] == 1004
    assert colors["_pairs"] == {}


def test_style_attr_caches_and_combines_styles(monkeypatch):
    mod = fake_curses()
    monkeypatch.setitem(sys.modules, "curses", mod)
    colors = tui_mod._init_colors()
    assert tui_mod._style_attr(colors, None) == 0
    assert tui_mod._style_attr({}, "red") == 0  # no colour support: plain text
    attr = tui_mod._style_attr(colors, "red")
    assert attr == mod.color_pair(5)  # first pair after the four chrome pairs
    assert tui_mod._style_attr(colors, "red") == attr  # cached
    assert tui_mod._style_attr(colors, "bold") == mod.A_BOLD
    both = tui_mod._style_attr(colors, "white/blue+bold")
    assert both & mod.A_BOLD and both & mod.color_pair(6)


def test_style_attr_survives_exhausted_color_pairs(monkeypatch):
    mod = fake_curses()

    def init_pair(number, fg, bg):
        if number >= 5:
            raise mod.error()

    mod.init_pair = init_pair
    monkeypatch.setitem(sys.modules, "curses", mod)
    colors = tui_mod._init_colors()
    assert tui_mod._style_attr(colors, "green") == 0


def test_draw_colours_the_picture_inside_the_view_box(monkeypatch):
    mod = fake_curses(size=(10, 40))
    monkeypatch.setitem(sys.modules, "curses", mod)
    colors = tui_mod._init_colors()
    lines = ["H" * 40, "T" * 30 + "[c]:Camera", "r2" + " " * 37, "r3" + " " * 37,
             "r4" + " " * 37, "status", "foot [q] Quit"]
    styles = [["red", None], ["bold", "white/blue"]]
    tui_mod._draw(mod._screen, lines, (2, 5, 4, 10), colors, styles, footer_rows=2)
    added = [call for call in mod._screen.calls if call[0] == "addstr"]
    assert added and all(call[1] > 2 for call in added)  # inside the box, below the header
    addnstr = [call for call in mod._screen.calls if call[0] == "addnstr"]
    assert any("[c]:Camera" in call[3] for call in addnstr)  # active tab highlighted
    assert any("[q]" in call[3] for call in addnstr)  # footer key highlighted


def test_draw_ignores_curses_write_errors(monkeypatch):
    mod = fake_curses(size=(6, 20))

    def broken(*args):
        raise mod.error()

    mod._screen.addnstr = broken
    mod._screen.addstr = broken
    monkeypatch.setitem(sys.modules, "curses", mod)
    colors = {"header": 1, "shortcut": 2, "status": 3, "commands": 4, "_pairs": {}}
    lines = ["H" * 20, "T" * 20, "body", "body2", "status", "foot [q]"]
    tui_mod._draw(mod._screen, lines, (2, 2, 3, 6), colors, [["red"]], footer_rows=2)
    assert ("refresh",) in mod._screen.calls
