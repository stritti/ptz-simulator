# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""End-to-end tests over real sockets and a pty."""

import asyncio
import os
import socket
import struct

import pytest

from ptzsim.cli import send_packets
from ptzsim.display import render
from ptzsim.transports import (SONY_CONTROL_COMMAND, SONY_CONTROL_REPLY, SONY_HEADER, SONY_VISCA_COMMAND,
                                SONY_VISCA_INQUIRY, Simulator, SonyViscaIpProtocol, serve_pty, serve_tcp,
                                serve_udp)
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


def test_completions_carry_their_socket_and_axes():
    sim = Simulator(ViscaCamera(), tick_interval=0.01)
    out = []
    sim.process(parse_hex("81 01 06 02 01 01 00 01 00 00 00 00 00 00 FF"), out.append)  # slow pan
    sim.process(parse_hex("81 01 04 47 00 08 00 00 FF"), out.append)  # short zoom
    assert out == [parse_hex("90 41 FF"), parse_hex("90 42 FF")]
    sim.step(0.5)  # zoom has arrived, pan has not
    assert out[-1] == parse_hex("90 52 FF") and len(out) == 3
    sim.process(parse_hex("81 22 FF"), out.append)  # socket 2 is free again
    assert out[-1] == parse_hex("90 62 05 FF")
    sim.process(parse_hex("81 21 FF"), out.append)
    assert out[-1] == parse_hex("90 61 04 FF")
    sim.step(100)
    assert out[-1] == parse_hex("90 61 04 FF")  # no completion after the cancel


def test_if_clear_drops_waiting_completion():
    sim = Simulator(ViscaCamera(), tick_interval=0.01)
    out = []
    sim.process(parse_hex("81 01 06 02 01 01 00 01 00 00 00 00 00 00 FF"), out.append)
    sim.process(parse_hex("88 01 00 01 FF"), out.append)
    sim.step(100)
    assert out == [parse_hex("90 41 FF"), parse_hex("88 01 00 01 FF")]
    assert not sim.camera.sockets


def test_newer_move_supersedes_older_socket():
    sim = Simulator(ViscaCamera(), tick_interval=0.01)
    out = []
    sim.process(parse_hex("81 01 06 02 01 01 00 01 00 00 00 00 00 00 FF"), out.append)  # pan 256
    sim.process(parse_hex("81 01 06 02 01 01 00 02 00 00 00 00 00 00 FF"), out.append)  # pan 512
    sim.step(0.01)
    # socket 1 lost its axes to socket 2 and completes; cancelling it finds nothing
    assert out == [parse_hex("90 41 FF"), parse_hex("90 42 FF"), parse_hex("90 51 FF")]
    sim.process(parse_hex("81 21 FF"), out.append)
    assert out[-1] == parse_hex("90 61 05 FF")
    assert sim.camera.state.pan_target is not None  # socket 2 keeps moving
    sim.step(100)
    assert out[-1] == parse_hex("90 52 FF") and sim.camera.state.position()[0] == 512


class FakeTransport:
    def __init__(self):
        self.sent = []

    def sendto(self, data, addr):
        self.sent.append(data)


def sony(payload_type, sequence, hex_packet):
    packet = parse_hex(hex_packet)
    return SONY_HEADER.pack(payload_type, len(packet), sequence) + packet


def sony_protocol():
    protocol = SonyViscaIpProtocol(Simulator(ViscaCamera(instant=True)))
    protocol.connection_made(FakeTransport())
    return protocol


def test_sony_ip_repeated_sequence_is_not_executed_again():
    protocol = sony_protocol()
    home = sony(SONY_VISCA_COMMAND, 7, "81 01 06 04 FF")
    protocol.datagram_received(home, ("10.0.0.1", 1))
    protocol.datagram_received(home, ("10.0.0.1", 1))
    assert protocol.transport.sent[-1] == SONY_HEADER.pack(SONY_CONTROL_REPLY, 2, 7) + b""
    assert len(protocol.transport.sent) == 3  # ACK, completion, sequence error
    # after a RESET the same number is fine again
    protocol.datagram_received(SONY_HEADER.pack(SONY_CONTROL_COMMAND, 1, 0) + b"", ("10.0.0.1", 1))
    protocol.datagram_received(home, ("10.0.0.1", 1))
    assert protocol.transport.sent[-1][8:] == parse_hex("90 51 FF")


def test_sony_ip_wrong_message_type():
    protocol = sony_protocol()
    protocol.datagram_received(sony(SONY_VISCA_COMMAND, 1, "81 09 06 12 FF"), ("10.0.0.1", 1))
    protocol.datagram_received(sony(SONY_VISCA_INQUIRY, 2, "81 01 06 04 FF"), ("10.0.0.1", 1))
    assert [d[8:] for d in protocol.transport.sent] == [b"", b""]


def test_sony_ip_any_address_counts_as_camera_1():
    protocol = sony_protocol()
    protocol.datagram_received(sony(SONY_VISCA_COMMAND, 1, "83 01 06 04 FF"), ("10.0.0.1", 1))
    assert [d[8:] for d in protocol.transport.sent] == [parse_hex("90 41 FF"), parse_hex("90 51 FF")]


def test_sony_ip_retransmission_after_error_is_executed_again():
    protocol = sony_protocol()
    camera = protocol.sim.camera
    camera.state.power = False
    home = sony(SONY_VISCA_COMMAND, 9, "81 01 06 04 FF")
    protocol.datagram_received(home, ("10.0.0.1", 1))
    assert protocol.transport.sent[-1][8:] == parse_hex("90 61 41 FF")
    camera.state.power = True  # error cause removed
    protocol.datagram_received(home, ("10.0.0.1", 1))
    assert [d[8:] for d in protocol.transport.sent[-2:]] == [parse_hex("90 41 FF"), parse_hex("90 51 FF")]


def test_sony_ip_retransmitted_cancel_is_not_executed_again():
    protocol = Simulator(ViscaCamera())
    protocol = SonyViscaIpProtocol(protocol)
    protocol.connection_made(FakeTransport())
    peer = ("10.0.0.1", 1)
    protocol.datagram_received(sony(SONY_VISCA_COMMAND, 1, "81 01 06 02 01 01 00 01 00 00 00 00 00 00 FF"), peer)
    cancel = sony(SONY_VISCA_COMMAND, 2, "81 21 FF")
    protocol.datagram_received(cancel, peer)
    assert protocol.transport.sent[-1][8:] == parse_hex("90 61 04 FF")
    protocol.datagram_received(cancel, peer)
    assert protocol.transport.sent[-1] == SONY_HEADER.pack(SONY_CONTROL_REPLY, 2, 2) + b"\x0f\x01"
