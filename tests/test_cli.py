# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Tests for the command line interface: ptzsim.cli (serve/send) and ptzsim.__main__."""

import asyncio
import builtins
import logging
import os
import runpy
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from ptzsim import cli
from ptzsim.cli import DEFAULT_PORTS, _is_final, build_parser, main, send_packets
from ptzsim.testing import free_port, serve
from ptzsim.visca import parse_hex


# ------------------------------------------------------------------- parser
def test_serve_parser_defaults():
    args = build_parser().parse_args(["serve"])
    assert args.command == "serve"
    assert args.host == "0.0.0.0" and args.name == "PTZ-Simulator"
    assert args.address == 1 and not args.instant and not args.no_tui and not args.view_only
    assert not args.verbose


def test_send_parser_defaults():
    args = build_parser().parse_args(["send", "81 09 06 12 FF"])
    assert args.command == "send"
    assert args.proto == "sony" and args.port is None and args.host == "127.0.0.1"
    assert args.timeout == 2.0


# ------------------------------------------------------------- reply helpers
@pytest.mark.parametrize("reply, final", [
    (parse_hex("90 50 FF"), True),      # completion
    (parse_hex("90 51 00 FF"), True),   # inquiry answer
    (parse_hex("90 60 02 FF"), True),   # error
    (b"\x88\x01\x00\xff", True),        # Sony sequence error
    (parse_hex("90 41 FF"), False),     # ACK
    (b"", False),
    (b"\x90", False),
])
def test_is_final(reply, final):
    assert _is_final(reply) is final


def test_collect_stream_timeout_ack_final_and_eof():
    a, b = socket.socketpair()
    try:
        a.settimeout(0.05)
        assert cli._collect_stream(a, 0.05) == []  # nothing arrives: timeout
        b.sendall(parse_hex("90 41 FF"))  # ACK is not final
        assert cli._collect_stream(a, 0.05) == [parse_hex("90 41 FF")]
        b.sendall(parse_hex("90 50 00 FF"))
        assert cli._collect_stream(a, 0.05) == [parse_hex("90 50 00 FF")]  # final reply stops
        b.close()
        assert cli._collect_stream(a, 0.05) == []  # EOF ends the stream
    finally:
        a.close()
        b.close()


def test_collect_stream_splits_multiple_replies_in_one_chunk():
    a, b = socket.socketpair()
    try:
        a.settimeout(0.05)
        b.sendall(parse_hex("90 41 FF 90 50 FF"))
        assert cli._collect_stream(a, 0.05) == [parse_hex("90 41 FF"), parse_hex("90 50 FF")]
    finally:
        a.close()
        b.close()


def test_collect_datagrams_strips_sony_header_and_times_out():
    a, b = socket.socketpair()
    try:
        a.settimeout(0.05)
        payload = parse_hex("90 50 FF")
        b.sendall(cli.SONY_HEADER.pack(0x0111, len(payload), 1) + payload)
        assert cli._collect_datagrams(a, sony=True) == [payload]
        ack = parse_hex("90 41 FF")
        b.sendall(cli.SONY_HEADER.pack(0x0111, len(ack), 2) + ack)
        assert cli._collect_datagrams(a, sony=True) == [ack]  # ACK: wait for more, then timeout
        b.sendall(parse_hex("90 50 FF"))
        assert cli._collect_datagrams(a, sony=False) == [parse_hex("90 50 FF")]  # raw VISCA
    finally:
        a.close()
        b.close()


# ------------------------------------------------- send against a live camera
def test_send_packets_tcp_roundtrip():
    async def run():
        port = free_port()
        async with serve("--tcp", str(port)):
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None, send_packets, [parse_hex("81 09 06 12 FF")], "127.0.0.1", port, "tcp", 1.0)

    assert asyncio.run(run()) == [parse_hex("90 50 00 00 00 00 00 00 00 00 FF")]


def test_main_send_prints_replies(capsys):
    async def run():
        port = free_port()
        async with serve("--tcp", str(port)):
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None, main, ["send", "81 09 06 12 FF", "--host", "127.0.0.1",
                            "--port", str(port), "--proto", "tcp", "--timeout", "1"])

    assert asyncio.run(run()) == 0
    out = capsys.readouterr().out
    assert out.strip() == "90 50 00 00 00 00 00 00 00 00 FF"


def test_main_send_uses_default_port_of_the_protocol(monkeypatch, capsys):
    async def run():
        port = free_port()
        async with serve("--tcp", str(port)):
            monkeypatch.setitem(DEFAULT_PORTS, "tcp", port)
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None, main, ["send", "81 09 06 12 FF", "--proto", "tcp", "--timeout", "1"])

    assert asyncio.run(run()) == 0
    assert "90 50" in capsys.readouterr().out


# --------------------------------------------------------------------- serve
def serve_args(*argv):
    return build_parser().parse_args(["serve", "--host", "127.0.0.1", *argv])


async def _instant_view(camera, **kwargs):
    camera.record("test", "view started")
    return  # the view ending makes _serve return


def test_serve_no_tui_starts_plugins_and_returns_when_view_ends(monkeypatch, caplog):
    monkeypatch.setattr(cli, "log_printer", _instant_view)
    with caplog.at_level(logging.INFO, logger="ptzsim"):
        asyncio.run(cli._serve(serve_args("--no-tui", "--tcp", "0")))
    assert any("listening" in r.message for r in caplog.records)


def test_serve_on_all_interfaces_logs_resolved_addresses(monkeypatch, caplog):
    monkeypatch.setattr(cli, "log_printer", _instant_view)
    args = build_parser().parse_args(["serve", "--no-tui", "--tcp", "0"])  # host 0.0.0.0
    with caplog.at_level(logging.INFO, logger="ptzsim"):
        asyncio.run(cli._serve(args))
    messages = [r.message for r in caplog.records]
    assert any(m.startswith("Available on: ") for m in messages)
    assert any("Hostname:" in m for m in messages)


def test_serve_view_only_uses_the_dashboard(monkeypatch):
    seen = {}

    async def fake_dashboard(camera, title, **kwargs):
        seen["title"] = title

    monkeypatch.setattr(cli, "dashboard", fake_dashboard)
    asyncio.run(cli._serve(serve_args("--view-only", "--tcp", "0")))
    assert "VISCA" in seen["title"]


def test_serve_interactive_terminal_uses_the_tui(monkeypatch):
    seen = {}

    async def fake_interactive(camera, title):
        seen["title"] = title

    monkeypatch.setattr(cli, "_interactive_terminal", lambda: True)
    monkeypatch.setattr("ptzsim.tui.interactive", fake_interactive)
    asyncio.run(cli._serve(serve_args("--tcp", "0")))
    assert "VISCA" in seen["title"]


def test_serve_reraises_errors_from_the_view(monkeypatch):
    async def broken_view(camera, **kwargs):
        raise RuntimeError("view exploded")

    monkeypatch.setattr(cli, "log_printer", broken_view)
    with pytest.raises(RuntimeError, match="view exploded"):
        asyncio.run(cli._serve(serve_args("--no-tui", "--tcp", "0")))


def test_main_serve_returns_zero(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "log_printer", _instant_view)
    assert main(["serve", "--host", "127.0.0.1", "--no-tui", "--tcp", "0"]) == 0


def test_main_serve_reports_binding_errors(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen()
    port = blocker.getsockname()[1]
    try:
        rc = main(["serve", "--host", "127.0.0.1", "--no-tui", "--tcp", str(port)])
    finally:
        blocker.close()
    assert rc == 1
    err = capsys.readouterr().err
    assert f"cannot listen on port {port}" in err and "already in use" in err
    assert "--tcp <PORT>" in err


def test_main_serve_ignores_keyboard_interrupt(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_serve", lambda args: None)  # no coroutine is created

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(asyncio, "run", interrupted)
    assert main(["serve", "--host", "127.0.0.1", "--no-tui", "--tcp", "0"]) == 0


# ------------------------------------------------------ terminal detection
class FakeTty:
    def __init__(self, tty):
        self._tty = tty

    def isatty(self):
        return self._tty


def test_interactive_terminal_needs_curses_and_two_ttys(monkeypatch):
    pytest.importorskip("curses")
    monkeypatch.setattr(sys, "stdin", FakeTty(True))
    monkeypatch.setattr(sys, "stdout", FakeTty(True))
    assert cli._interactive_terminal() is True
    monkeypatch.setattr(sys, "stdout", FakeTty(False))
    assert cli._interactive_terminal() is False


def test_interactive_terminal_false_without_curses(monkeypatch):
    real_import = builtins.__import__

    def no_curses(name, *args, **kwargs):
        if name == "curses":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_curses)
    assert cli._interactive_terminal() is False


def test_curses_hint_names_windows_curses_on_windows(monkeypatch):
    monkeypatch.setattr(cli, "_has_curses", lambda: False)
    monkeypatch.setattr(sys, "platform", "win32")
    assert "pip install windows-curses" in cli._curses_hint()
    monkeypatch.setattr(sys, "platform", "linux")
    assert "windows-curses" not in cli._curses_hint()
    monkeypatch.setattr(cli, "_has_curses", lambda: True)
    assert cli._curses_hint() is None  # curses there, only no terminal: nothing to install


@pytest.mark.parametrize("extra, expected", [((), True), (("--view-only",), False)])
def test_dashboard_says_why_keyboard_control_is_missing(monkeypatch, extra, expected):
    seen = {}

    async def fake_dashboard(camera, title, **kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(cli, "dashboard", fake_dashboard)
    monkeypatch.setattr(cli, "_has_curses", lambda: False)
    asyncio.run(cli._serve(serve_args("--tcp", "0", *extra)))
    assert bool(seen["notice"] and "curses" in seen["notice"]) is expected


# ------------------------------------------------------------- module entry
def test_main_module_entry_point_runs_cli(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["ptzsim", "--help"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("ptzsim.__main__", run_name="__main__", alter_sys=True)
    assert exc.value.code == 0
    assert "serve" in capsys.readouterr().out


def test_cli_module_guard(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["ptzsim", "--help"])
    monkeypatch.delitem(sys.modules, "ptzsim.cli", raising=False)  # avoid the runpy warning
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("ptzsim.cli", run_name="__main__", alter_sys=True)
    assert exc.value.code == 0
    assert "send" in capsys.readouterr().out


def test_python_m_ptzsim_help():
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    result = subprocess.run([sys.executable, "-m", "ptzsim", "--help"],
                            capture_output=True, text=True, timeout=10, env=env)
    assert result.returncode == 0, result.stderr
    assert "serve" in result.stdout and "send" in result.stdout
