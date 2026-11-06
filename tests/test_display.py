# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Unit tests for the dashboard rendering and keyboard handling (ptzsim.display)."""

import asyncio
import builtins
import io
import logging
import os
import select
import sys
import time

import pytest

from ptzsim import display
from ptzsim.network import InterfaceInfo
from ptzsim.visca import ViscaCamera


def make_interface(name, up=True, ipv4=(), ipv6=(), loopback=False):
    info = InterfaceInfo(name)
    info.up = up
    info.loopback = loopback
    for address, netmask in ipv4:
        info.add_ipv4(address, netmask)
    for address in ipv6:
        info.add_ipv6(address)
    return info


# ------------------------------------------------------------------ bar/picture
def test_bar_marks_position_center_and_clamps():
    assert display.bar(5, 0, 10, width=11).index("●") == 6  # round(5/10*10) + "["
    assert display.bar(0, 0, 10, width=11).index("●") == 1
    assert display.bar(100, 0, 10, width=11).index("●") == 11  # clamped to the end
    assert display.bar(-100, 0, 10, width=11).index("●") == 1  # clamped to the start
    centered = display.bar(5, -10, 10, width=21, center=True)
    assert centered.index("┼") == 11  # zero mark at the centre
    assert centered.index("●") == 16  # value mark right of it


def test_render_camera_shows_state_presets_and_log():
    cam = ViscaCamera()
    cam.state.drive_pan_tilt(1, 0, 2, 1)
    cam.state.save_preset(0, name="gate")
    cam.state.last_preset = 0
    cam.record("TEST", "did something", ok=False)
    text = display.render_camera(cam, "my title", color=False)
    assert "PTZ camera simulator" in text and "my title" in text
    assert "Power: ON" in text and f"Address: {cam.address}" in text and "Commands: 1" in text
    assert "▶" in text  # pan is moving
    assert "*  1:" in text and "gate" in text  # last preset marked with *
    assert "did something" in text


def test_render_camera_standby_empty_log_and_move_target():
    cam = ViscaCamera()
    cam.state.power = False
    text = display.render_camera(cam, "t", color=False)
    assert "STANDBY" in text and "(waiting for commands)" in text and "No presets stored" in text
    cam.state.power = True
    cam.state.pan_target = (500.0, 60.0)
    text = display.render_camera(cam, "t", color=False)
    assert "→ 500" in text  # absolute move target


def test_render_camera_color_adds_ansi_codes():
    cam = ViscaCamera()
    assert "\x1b[" in display.render_camera(cam, "t", color=True)
    assert "\x1b[" not in display.render_camera(cam, "t", color=False)


def test_ipv4_with_prefix_falls_back_on_invalid_netmask():
    assert display._ipv4_with_prefix("10.0.0.1", "255.255.0.0") == "10.0.0.1/16"
    assert display._ipv4_with_prefix("10.0.0.1", "not-a-mask") == "10.0.0.1"


# -------------------------------------------------------------------- network
def test_render_network_without_interfaces(monkeypatch):
    monkeypatch.setattr(display, "get_all_interfaces_detailed", lambda: {})
    text = display.render_network("t", color=False)
    assert "(no network interfaces found)" in text
    assert "Interfaces (0)" in text


def test_render_network_lists_states_and_addresses(monkeypatch):
    interfaces = {
        "eth0": make_interface("eth0", ipv4=[("10.1.2.3", "255.255.255.0")], ipv6=["fe80::1"]),
        "eth1": make_interface("eth1", up=False),
        "lo": make_interface("lo", up=None, ipv4=[("127.0.0.1", "255.0.0.0")], loopback=True),
    }
    monkeypatch.setattr(display, "get_all_interfaces_detailed", lambda: interfaces)
    text = display.render_network("t", color=False)
    assert "Interfaces (3)" in text
    assert "eth0" in text and "up" in text and "10.1.2.3/24" in text and "fe80::1" in text
    assert "down" in text and "–" in text  # eth1 has no addresses
    row = next(line for line in text.splitlines() if line.strip().startswith("lo"))
    assert row.split()[1] == "?"  # state unknown


def test_render_network_color_adds_ansi_codes(monkeypatch):
    monkeypatch.setattr(display, "get_all_interfaces_detailed", lambda: {})
    assert "\x1b[" in display.render_network("t", color=True)


def test_render_shortcuts_marks_the_active_view():
    camera = display.render_shortcuts(color=False, current_view="camera")
    network = display.render_shortcuts(color=False, current_view="network")
    assert "[c]:Camera" in camera and "n:Network" in camera
    assert "[n]:Network" in network and "c:Camera" in network
    assert "q:Quit" in camera
    assert "\x1b[" in display.render_shortcuts(color=True, current_view="camera")


def test_render_picks_view_and_adds_footer(monkeypatch):
    monkeypatch.setattr(display, "get_all_interfaces_detailed", lambda: {})
    cam = ViscaCamera()
    camera_view = display.render(cam, "t", color=False, view="camera")
    network_view = display.render(cam, "t", color=False, view="network")
    assert "PTZ camera simulator" in camera_view
    assert "Network Information" in network_view
    assert "─" * 120 in camera_view
    assert "[c]:Camera" in camera_view and "q:Quit" in camera_view


# -------------------------------------------------------------- dashboard state
def test_dashboard_state_switches_and_toggles_view():
    state = display.DashboardState()
    assert state.current_view == "camera" and not state.should_quit
    state.switch_view("network")
    assert state.current_view == "network"
    state.switch_view("bogus")  # ignored
    assert state.current_view == "network"
    state.toggle_view()
    assert state.current_view == "camera"
    state.current_view = "network"
    assert state.current_view == "network"
    state.should_quit = True
    assert state.should_quit


# -------------------------------------------------------------- keyboard input
class _PipeStdin:
    def __init__(self, fd, tty=False):
        self._fd = fd
        self._tty = tty

    def fileno(self):
        return self._fd

    def isatty(self):
        return self._tty


def _run_keyboard_input(state, timeout=3):
    async def run():
        await asyncio.wait_for(
            display.read_keyboard_input(state, asyncio.get_running_loop()), timeout)
    asyncio.run(run())


def _wait_until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "keyboard input did not react in time"
        time.sleep(0.01)


def test_keyboard_input_switches_views_and_quits(monkeypatch):
    read_fd, write_fd = os.pipe()
    monkeypatch.setattr(sys, "stdin", _PipeStdin(read_fd))
    state = display.DashboardState()
    try:
        async def run():
            task = asyncio.create_task(
                display.read_keyboard_input(state, asyncio.get_running_loop()))
            await asyncio.sleep(0.2)
            os.write(write_fd, b"n")
            await asyncio.get_running_loop().run_in_executor(None, _wait_until,
                                                             lambda: state.current_view == "network")
            os.write(write_fd, b"C")  # upper case is lowered
            await asyncio.get_running_loop().run_in_executor(None, _wait_until,
                                                             lambda: state.current_view == "camera")
            os.write(write_fd, b"\x03")  # Ctrl+C quits the dashboard
            await asyncio.wait_for(task, 2)
        asyncio.run(run())
        assert state.should_quit
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_keyboard_input_without_file_descriptor(monkeypatch):
    class NoFd:
        def fileno(self):
            raise ValueError("no fd")

    monkeypatch.setattr(sys, "stdin", NoFd())
    _run_keyboard_input(display.DashboardState())  # returns immediately


def test_keyboard_input_without_termios_module(monkeypatch):
    real_import = builtins.__import__

    def no_termios(name, *args, **kwargs):
        if name in ("termios", "tty"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_termios)
    _run_keyboard_input(display.DashboardState())  # returns immediately


def test_keyboard_input_survives_interrupted_select(monkeypatch):
    read_fd, write_fd = os.pipe()
    monkeypatch.setattr(sys, "stdin", _PipeStdin(read_fd))
    real_select = select.select
    calls = {"n": 0}

    def flaky_select(rlist, wlist, xlist, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise InterruptedError
        return real_select(rlist, wlist, xlist, timeout)

    monkeypatch.setattr(select, "select", flaky_select)
    state = display.DashboardState()
    try:
        async def run():
            task = asyncio.create_task(
                display.read_keyboard_input(state, asyncio.get_running_loop()))
            await asyncio.sleep(0.2)
            os.write(write_fd, b"q")
            await asyncio.wait_for(task, 2)
        asyncio.run(run())
        assert state.should_quit and calls["n"] >= 2
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_keyboard_input_logs_read_errors(monkeypatch, caplog):
    read_fd, write_fd = os.pipe()
    monkeypatch.setattr(sys, "stdin", _PipeStdin(read_fd))

    def broken_read(fd, size):
        raise OSError("gone")

    monkeypatch.setattr(os, "read", broken_read)
    state = display.DashboardState()
    try:
        os.write(write_fd, b"x")  # makes select report the fd readable
        with caplog.at_level(logging.WARNING, logger="ptzsim"):
            _run_keyboard_input(state)
        assert any("keyboard input stopped" in r.message for r in caplog.records)
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_keyboard_input_warns_when_terminal_restore_fails(monkeypatch, caplog):
    import termios
    import tty

    read_fd, write_fd = os.pipe()
    monkeypatch.setattr(sys, "stdin", _PipeStdin(read_fd, tty=True))
    monkeypatch.setattr(termios, "tcgetattr", lambda fd: [0] * 7)
    monkeypatch.setattr(tty, "setcbreak", lambda fd: None)

    def broken_restore(fd, when, attrs):
        raise termios.error("nope")

    monkeypatch.setattr(termios, "tcsetattr", broken_restore)
    state = display.DashboardState()
    try:
        async def run():
            task = asyncio.create_task(
                display.read_keyboard_input(state, asyncio.get_running_loop()))
            await asyncio.sleep(0.2)
            os.write(write_fd, b"q")
            await asyncio.wait_for(task, 2)
        with caplog.at_level(logging.WARNING, logger="ptzsim"):
            asyncio.run(run())
        assert any("Could not restore" in r.message for r in caplog.records)
    finally:
        os.close(read_fd)
        os.close(write_fd)


# -------------------------------------------------------------------- views
async def _quit_soon(state, loop):
    await asyncio.sleep(0.05)
    state.should_quit = True


def test_dashboard_renders_until_quit(monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(display, "read_keyboard_input", _quit_soon)
    cam = ViscaCamera()
    asyncio.run(display.dashboard(cam, "title", interval=0.01))
    text = out.getvalue()
    assert display.HIDE_CURSOR in text and display.SHOW_CURSOR in text
    assert "PTZ camera simulator" in text


def test_dashboard_survives_keyboard_interrupt(monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    real_render = display.render
    calls = {"n": 0}

    def interrupting_render(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1:
            raise KeyboardInterrupt
        return real_render(*args, **kwargs)

    async def never_ending_keyboard(state, loop):
        await asyncio.sleep(30)

    monkeypatch.setattr(display, "render", interrupting_render)
    monkeypatch.setattr(display, "read_keyboard_input", never_ending_keyboard)
    asyncio.run(display.dashboard(ViscaCamera(), "t", interval=0.01))
    assert display.SHOW_CURSOR in out.getvalue()


def test_log_printer_prints_only_new_commands(capsys):
    cam = ViscaCamera()
    cam.record("TEST", "first command")

    async def run():
        task = asyncio.create_task(display.log_printer(cam, interval=0.01))
        await asyncio.sleep(0.1)
        cam.record("TEST", "second command")
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    out = capsys.readouterr().out
    assert "first command" in out and "second command" in out
    assert "pan=0" in out and "zoom=0x0000" in out
    assert out.count("first command") == 1  # printed once, not repeated
