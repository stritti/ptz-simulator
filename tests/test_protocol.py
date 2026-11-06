# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Protocol plugin interface: registry, CLI wiring, built-in plugins and the
example plugin from docs/adding-a-protocol.md."""

import argparse
import os
import asyncio
import re
import socket
import types
from pathlib import Path

import pytest

from ptzsim import protocol
from ptzsim.builtin_protocols import Ndi, SonyViscaIp
from ptzsim.cli import build_parser, send_packets
from ptzsim.testing import free_port, serve
from ptzsim.visca import parse_hex

GUIDE = Path(__file__).resolve().parent.parent / "docs" / "adding-a-protocol.md"


def serve_args(*argv):
    return build_parser().parse_args(["serve", *argv])


@pytest.fixture
def isolated_registry():
    """Undo any registration a test makes."""
    saved = dict(protocol._registry), protocol._loaded
    yield
    protocol._registry.clear()
    protocol._registry.update(saved[0])
    protocol._loaded = saved[1]


@pytest.fixture
def example_plugin(isolated_registry):
    """Run the example plugin from the developer guide, exactly as printed there."""
    text = GUIDE.read_text(encoding="utf-8")
    code = re.search(r"<!-- example: text_protocol.py -->\s*```python\n(.*?)```", text, re.S).group(1)
    module = types.ModuleType("text_protocol")
    exec(compile(code, str(GUIDE), "exec"), module.__dict__)
    return module


# ----------------------------------------------------------------- registry
def test_builtin_plugins_in_option_order():
    assert [p.name for p in protocol.plugins()] == ["sony", "tcp", "udp", "pty", "onvif", "ndi"]


def test_sony_is_started_when_no_protocol_is_given():
    args = serve_args()
    assert protocol.selected(args) == [SonyViscaIp]
    assert args.sony == 52381


def test_default_is_not_added_to_an_explicit_choice():
    args = serve_args("--ndi")
    assert protocol.selected(args) == [Ndi]
    assert args.sony is None


def test_selection_keeps_registration_order():
    args = serve_args("--onvif", "--tcp", "6000", "--sony")
    assert [p.name for p in protocol.selected(args)] == ["sony", "tcp", "onvif"]
    assert (args.sony, args.tcp, args.onvif) == (52381, 6000, 8080)


@pytest.mark.parametrize("plugin", protocol.plugins(), ids=lambda p: p.name)
def test_every_plugin_follows_the_interface(plugin):
    assert re.fullmatch(r"[a-z][a-z0-9-]*", plugin.name)
    assert plugin.title
    parser = argparse.ArgumentParser()
    group = parser.add_argument_group(plugin.title)
    plugin.add_arguments(group)
    assert group._group_actions, "a plugin needs at least one option to be switched on"
    assert not plugin.enabled(serve_args()), "plugins must be off unless asked for"
    assert plugin.enabled(serve_args(group._group_actions[0].option_strings[0]))


def test_options_are_grouped_under_the_plugin_title():
    help_text = build_parser()._subparsers._group_actions[0].choices["serve"].format_help()
    for plugin in protocol.plugins():
        assert f"\n{plugin.title}:\n" in help_text


def test_register_rejects_bad_plugins(isolated_registry):
    class Nameless(protocol.PortPlugin):
        pass

    class Clash(protocol.PortPlugin):
        name, title = "sony", "clash"

    class SecondDefault(protocol.PortPlugin):
        name, title, default = "second", "second default", True

    with pytest.raises(ValueError):
        protocol.register(Nameless)
    with pytest.raises(ValueError, match="already used"):
        protocol.register(Clash)
    with pytest.raises(ValueError, match="default"):
        protocol.register(SecondDefault)
    with pytest.raises(TypeError):
        protocol.register(object)


def test_entry_point_plugins_are_loaded(isolated_registry, monkeypatch):
    class Remote(protocol.PortPlugin):
        name, title, default_port = "remote", "remote protocol", 9999

    class EntryPoint:
        def __init__(self, name, obj):
            self.name, self.obj = name, obj

        def load(self):
            if isinstance(self.obj, Exception):
                raise self.obj
            return self.obj

    monkeypatch.setattr(protocol, "_entry_points",
                        lambda: [EntryPoint("broken", ImportError("missing")), EntryPoint("remote", Remote)])
    protocol._loaded = False
    assert protocol.plugins()[-1] is Remote
    assert serve_args("--remote").remote == 9999


# --------------------------------------------------------- built-in plugins
def test_builtin_endpoints_and_shutdown():
    async def run():
        tcp, onvif = free_port(), free_port()
        async with serve("--tcp", str(tcp), "--onvif", str(onvif), "--no-discovery") as ctx:
            titles, ports = [str(e) for e in ctx.endpoints], ctx.ports()
            replies = await ctx.loop.run_in_executor(
                None, send_packets, [parse_hex("81 09 06 12 FF")], "127.0.0.1", tcp, "tcp", 1.0)
        return tcp, onvif, titles, ports, replies

    tcp, onvif, titles, ports, replies = asyncio.run(run())
    assert titles == [f"VISCA tcp://127.0.0.1:{tcp}",
                      f"ONVIF http://127.0.0.1:{onvif}/onvif/device_service"]
    assert ports == {"VISCA/TCP": tcp, "ONVIF": onvif}
    assert replies == [parse_hex("90 50 00 00 00 00 00 00 00 00 FF")]
    with pytest.raises(OSError):  # servers are closed when the plugins stop
        socket.create_connection(("127.0.0.1", tcp), timeout=1).close()


def test_sony_endpoint_title():
    async def run():
        port = free_port(socket.SOCK_DGRAM)
        async with serve("--sony", str(port)) as ctx:
            return port, [str(e) for e in ctx.endpoints]

    port, titles = asyncio.run(run())
    assert titles == [f"Sony VISCA/IP udp://127.0.0.1:{port}"]


# ------------------------------------------------- example from the guide
def test_example_parser_without_sockets(example_plugin):
    from ptzsim.visca import ViscaCamera

    camera = ViscaCamera(instant=True)
    controller = example_plugin.TextController(camera)
    assert controller.handle("GOTO 10 -5") == "OK"
    assert controller.handle("ZOOM 1") == "OK"
    assert controller.handle("POS?") == "POS 10.0 -5.0 20.0"
    assert controller.handle("GOTO 10").startswith("ERR")
    assert controller.handle("JUMP").startswith("ERR")
    assert [(e.label, e.ok) for e in camera.log] == [("TEXT", True)] * 2 + [("TEXT", False)] * 2


def test_example_plugin_end_to_end(example_plugin):
    assert "--text [PORT]" in build_parser()._subparsers._group_actions[0].choices["serve"].format_help()

    async def run():
        port = free_port()
        async with serve("--text", str(port)) as ctx:
            def talk():
                with socket.create_connection(("127.0.0.1", port), timeout=1) as sock:
                    sock.sendall(b"GOTO 10 5\r\nPOS?\r\nSTOP\r\n")
                    data = b""
                    while data.count(b"\r\n") < 3:
                        data += sock.recv(64)
                    return data

            reply = await ctx.loop.run_in_executor(None, talk)
            return ctx, port, reply

    ctx, port, reply = asyncio.run(run())
    assert reply == b"OK\r\nPOS 10.0 5.0 1.0\r\nOK\r\n"
    assert [str(e) for e in ctx.endpoints] == [f"TEXT tcp://127.0.0.1:{port}"]
    assert ctx.camera.log[0].label == "TEXT"


def test_plugin_failing_during_start_is_stopped(isolated_registry):
    class HalfStarted(protocol.PortPlugin):
        name, title, default_port = "half", "half started", 1

        async def start(self, ctx):
            self.servers.append(await asyncio.start_server(lambda r, w: None, ctx.host, self.port(ctx.args)))
            raise OSError("second socket failed")

    protocol.register(HalfStarted)
    port = free_port()

    async def run():
        async with serve("--half", str(port)):
            pass

    with pytest.raises(OSError, match="second socket"):
        asyncio.run(run())
    with pytest.raises(OSError):  # the server opened before the failure is closed
        socket.create_connection(("127.0.0.1", port), timeout=1).close()


@pytest.mark.skipif(not hasattr(os, "openpty"), reason="pty needs POSIX")
def test_serial_plugin_releases_the_pty(tmp_path):
    link = tmp_path / "ttyPTZ"

    async def run():
        async with serve("--pty", str(link)) as ctx:
            assert [str(e) for e in ctx.endpoints] == [f"VISCA serial {link}"]
            port = ctx.plugins[0].servers[0]
            assert link.is_symlink()
            return port

    port = asyncio.run(run())
    assert (port.master, port.slave) == (-1, -1)
    assert not link.exists()


def test_port_can_be_reused_right_after_the_context():
    async def run():
        port = free_port(socket.SOCK_DGRAM)
        for _ in range(2):
            async with serve("--udp", str(port)):
                pass

    asyncio.run(run())


def test_onvif_plugin_announces_ws_discovery_and_says_bye_on_stop():
    async def run():
        port = free_port()
        async with serve("--onvif", str(port)) as ctx:  # --no-discovery not given
            return [str(e) for e in ctx.endpoints]

    titles = asyncio.run(run())
    assert any(t.startswith("ONVIF http://127.0.0.1:") for t in titles)
    assert "WS-Discovery udp/3702" in titles  # discovery endpoint added; stop() sent Bye
