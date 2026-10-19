"""End-to-end tests over real sockets and a pty."""

import asyncio
import os
import socket
import struct

import pytest

from ptzsim.cli import send_packets
from ptzsim.display import render
from ptzsim.transports import Simulator, serve_pty, serve_tcp, serve_udp
from ptzsim.visca import ViscaCamera, parse_hex


def free_port(kind=socket.SOCK_STREAM):
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def start(kind, instant=True):
    sim = Simulator(ViscaCamera(instant=instant), tick_interval=0.01)
    if kind == "tcp":
        port = free_port()
        await serve_tcp(sim, "127.0.0.1", port)
    else:
        port = free_port(socket.SOCK_DGRAM)
        await serve_udp(sim, "127.0.0.1", port, sony=kind == "sony")
    task = asyncio.ensure_future(sim.run())
    return sim, port, task


async def roundtrip(kind, packets, **kwargs):
    sim, port, task = await start(kind, **kwargs)
    try:
        replies = await asyncio.get_running_loop().run_in_executor(
            None, send_packets, [parse_hex(p) for p in packets], "127.0.0.1", port, kind, 1.0)
    finally:
        task.cancel()
    return sim, replies


@pytest.mark.parametrize("kind", ["tcp", "udp", "sony"])
def test_command_and_inquiry(kind):
    sim, replies = asyncio.run(roundtrip(kind, [
        "81 01 06 02 18 14 00 01 00 00 00 00 01 00 FF",
        "81 09 06 12 FF",
    ]))
    assert replies == [
        parse_hex("90 41 FF"), parse_hex("90 51 FF"),
        parse_hex("90 50 00 01 00 00 00 00 01 00 FF"),
    ]
    assert sim.camera.state.position()[:2] == (256, 16)


def test_completion_is_sent_after_motion_finishes():
    sim, replies = asyncio.run(roundtrip(
        "tcp", ["81 01 06 02 18 14 00 01 00 00 00 00 00 00 FF"], instant=False))
    assert replies == [parse_hex("90 41 FF"), parse_hex("90 51 FF")]
    assert sim.camera.state.position()[0] == 256


def test_sony_header_and_control_reset():
    async def run():
        sim, port, task = await start("sony")
        try:
            def talk():
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.settimeout(1)
                    s.sendto(struct.pack(">HHI", 0x0200, 1, 0) + b"\x01", ("127.0.0.1", port))
                    control = s.recv(64)
                    s.sendto(struct.pack(">HHI", 0x0110, 5, 42) + parse_hex("81 09 04 00 FF"),
                             ("127.0.0.1", port))
                    return control, s.recv(64)
            return await asyncio.get_running_loop().run_in_executor(None, talk)
        finally:
            task.cancel()

    control, reply = asyncio.run(run())
    assert control == struct.pack(">HHI", 0x0201, 1, 0) + b"\x01"
    assert reply == struct.pack(">HHI", 0x0111, 4, 42) + parse_hex("90 50 02 FF")


@pytest.mark.skipif(os.name != "posix", reason="pty needs POSIX")
def test_pty_serial():
    async def run():
        sim = Simulator(ViscaCamera(instant=True), tick_interval=0.01)
        path = serve_pty(sim)
        task = asyncio.ensure_future(sim.run())
        fd = os.open(path, os.O_RDWR | os.O_NOCTTY)
        try:
            os.write(fd, parse_hex("81 01 04 3F 01 07 FF"))
            data = b""
            for _ in range(50):
                await asyncio.sleep(0.02)
                try:
                    os.set_blocking(fd, False)
                    data += os.read(fd, 64)
                except BlockingIOError:
                    pass
                if len(data) >= 6:
                    break
            return sim, data
        finally:
            os.close(fd)
            task.cancel()

    sim, data = asyncio.run(run())
    assert data == parse_hex("90 41 FF 90 51 FF")
    assert 7 in sim.camera.state.presets


def test_render_shows_state():
    cam = ViscaCamera(instant=True)
    cam.handle(parse_hex("81 01 04 3F 01 03 FF"))
    text = render(cam, "test", color=False)
    assert "Pan" in text and "4: pan" in text and "preset 4 set" in text


def test_cancel_drops_waiting_completion():
    sim = Simulator(ViscaCamera(), tick_interval=0.01)
    out = []
    sim.process(parse_hex("81 01 06 02 18 14 00 01 00 00 00 00 00 00 FF"), out.append)
    sim.process(parse_hex("81 21 FF"), out.append)
    assert out == [parse_hex("90 41 FF"), parse_hex("90 61 04 FF")]
    sim.step(100)
    assert out == [parse_hex("90 41 FF"), parse_hex("90 61 04 FF")]
    assert not sim.camera.state.busy
    sim.process(parse_hex("81 21 FF"), out.append)
    assert out[-1] == parse_hex("90 61 05 FF")
