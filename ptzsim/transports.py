# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Network / serial transports carrying VISCA to the simulated camera."""

from __future__ import annotations

import asyncio
import logging
import os
import struct
import time
from typing import Callable, FrozenSet, List, Optional, Tuple

from .visca import ViscaCamera, hexdump, split_packets

log = logging.getLogger("ptzsim")

Send = Callable[[bytes], None]

# Sony VISCA over IP payload types.
SONY_VISCA_COMMAND = 0x0100
SONY_VISCA_INQUIRY = 0x0110
SONY_VISCA_REPLY = 0x0111
SONY_VISCA_DEVICE_SETTING = 0x0120
SONY_CONTROL_COMMAND = 0x0200
SONY_CONTROL_REPLY = 0x0201
SONY_HEADER = struct.Struct(">HHI")
# Control reply "ERROR": abnormality in the sequence number / in the message type.
ERROR_SEQUENCE = b"\x0f\x01"
ERROR_MESSAGE_TYPE = b"\x0f\x02"


class Simulator:
    """Runs the camera physics and routes replies back to the senders."""

    def __init__(self, camera: ViscaCamera, tick_interval: float = 0.02):
        self.camera = camera
        self.tick_interval = tick_interval
        # Completions waiting for motion: (sender, reply, socket, axes).
        self._pending: List[Tuple[Send, bytes, Optional[int], FrozenSet[str]]] = []
        self.clients = 0

    def process(self, packet: bytes, send: Send) -> None:
        log.debug("rx %s", hexdump(packet))
        self._flush()  # completions that are due go out before the next reply
        for reply in self.camera.handle(packet):
            if reply.clear_buffers:
                self._pending = []
            if reply.cancel_socket is not None:
                self._pending = [p for p in self._pending if p[2] != reply.cancel_socket]
            if reply.after_motion:
                self._pending.append((send, reply.data, reply.socket, reply.axes))
            else:
                self._send(send, reply.data)

    def _send(self, send: Send, data: bytes) -> None:
        log.debug("tx %s", hexdump(data))
        try:
            send(data)
        except (OSError, RuntimeError) as err:  # client went away
            log.debug("send failed: %s", err)

    def _flush(self) -> None:
        """Send every completion whose axes have stopped moving."""
        state = self.camera.state
        due = [p for p in self._pending if not state.axes_busy(p[3])]
        if due:
            self._pending = [p for p in self._pending if state.axes_busy(p[3])]
            for send, data, _, _ in due:
                self._send(send, data)

    def step(self, dt: float) -> None:
        self.camera.state.tick(dt)
        self._flush()

    async def run(self) -> None:
        last = time.monotonic()
        while True:
            await asyncio.sleep(self.tick_interval)
            now = time.monotonic()
            self.step(now - last)
            last = now


# ---------------------------------------------------------------- raw TCP
async def serve_tcp(sim: Simulator, host: str, port: int) -> asyncio.AbstractServer:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        log.info("TCP client connected: %s", peer)
        sim.clients += 1
        buffer = bytearray()
        try:
            while data := await reader.read(1024):
                buffer.extend(data)
                for packet in split_packets(buffer):
                    sim.process(packet, writer.write)
        except ConnectionError:
            pass
        finally:
            sim.clients -= 1
            log.info("TCP client disconnected: %s", peer)
            writer.close()

    return await asyncio.start_server(handle, host, port)


# ---------------------------------------------------------------- raw UDP
class RawUdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, sim: Simulator):
        self.sim = sim
        self.transport: Optional[asyncio.DatagramTransport] = None

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        buffer = bytearray(data)
        for packet in split_packets(buffer):
            self.sim.process(packet, lambda reply, a=addr: self.transport.sendto(reply, a))


# ------------------------------------------------------- Sony VISCA over IP
class SonyViscaIpProtocol(asyncio.DatagramProtocol):
    """Sony "VISCA over IP": 8-byte header (type, length, sequence) + VISCA."""

    def __init__(self, sim: Simulator):
        self.sim = sim
        self.transport: Optional[asyncio.DatagramTransport] = None
        # Last sequence number per controller; a repeat is not executed again.
        self._last_sequence = {}

    def connection_made(self, transport) -> None:
        self.transport = transport

    def _reply(self, addr, payload_type: int, sequence: int, payload: bytes) -> None:
        header = SONY_HEADER.pack(payload_type, len(payload), sequence)
        self.transport.sendto(header + payload, addr)

    def datagram_received(self, data: bytes, addr) -> None:
        if len(data) < SONY_HEADER.size:
            log.warning("short Sony VISCA-IP datagram from %s: %s", addr, hexdump(data))
            return
        payload_type, length, sequence = SONY_HEADER.unpack_from(data)
        payload = data[SONY_HEADER.size:SONY_HEADER.size + length]

        if payload_type == SONY_CONTROL_COMMAND:
            # 0x01 = RESET of the sequence number; answer with an ACK.
            log.info("Sony VISCA-IP control command %s from %s", hexdump(payload), addr)
            if payload[:1] == b"\x01":
                self._last_sequence.pop(addr, None)
            self._reply(addr, SONY_CONTROL_REPLY, sequence, b"\x01")
            return
        if payload_type not in (SONY_VISCA_COMMAND, SONY_VISCA_INQUIRY, SONY_VISCA_DEVICE_SETTING):
            log.warning("unknown Sony VISCA-IP payload type %04X from %s", payload_type, addr)
            self._reply(addr, SONY_CONTROL_REPLY, sequence, ERROR_MESSAGE_TYPE)
            return
        # The message type must match the VISCA packet: 8x 01 .. command, 8x 09 .. inquiry.
        kind = payload[1:2]
        if (payload_type == SONY_VISCA_COMMAND and kind == b"\x09") or (
                payload_type == SONY_VISCA_INQUIRY and kind != b"\x09"):
            self._reply(addr, SONY_CONTROL_REPLY, sequence, ERROR_MESSAGE_TYPE)
            return
        # A retransmission with the same sequence number is not executed again.
        if self._last_sequence.get(addr) == sequence:
            self._reply(addr, SONY_CONTROL_REPLY, sequence, ERROR_SEQUENCE)
            return
        self._last_sequence[addr] = sequence

        errors = []

        def send(reply: bytes, a=addr, seq=sequence) -> None:
            if reply[1] & 0xF0 == 0x60:
                errors.append(reply)
            self._reply(a, SONY_VISCA_REPLY, seq, bytes([0x90]) + reply[1:])

        buffer = bytearray(payload)
        for packet in split_packets(buffer):
            # Over IP the camera address is fixed to 1 and the controller to 0:
            # any address is accepted and every reply comes from 90.
            if packet[0] & 0xF0 == 0x80 and packet[0] != 0x88:
                packet = bytes([0x80 | self.sim.camera.address]) + packet[1:]
            self.sim.process(packet, send)
        # Sony "Delivery confirmation": a message that was answered with an error was
        # not performed, so a retransmission with the same number is executed again.
        if errors:
            self._last_sequence.pop(addr, None)


async def serve_udp(sim: Simulator, host: str, port: int, sony: bool):
    loop = asyncio.get_running_loop()
    factory = (lambda: SonyViscaIpProtocol(sim)) if sony else (lambda: RawUdpProtocol(sim))
    transport, _ = await loop.create_datagram_endpoint(factory, local_addr=(host, port))
    return transport


# ------------------------------------------------------------ serial (pty)
def serve_pty(sim: Simulator, link: Optional[str] = None) -> str:
    """Open a pseudo terminal that behaves like the camera's RS-232/RS-422 port.

    Returns the path of the slave device a client can open like a serial port.
    """
    import termios
    import tty

    master, slave = os.openpty()
    tty.setraw(slave)
    attrs = termios.tcgetattr(slave)
    attrs[3] &= ~termios.ECHO
    termios.tcsetattr(slave, termios.TCSANOW, attrs)
    os.set_blocking(master, False)
    path = os.ttyname(slave)
    if link:
        if os.path.islink(link):
            os.unlink(link)
        os.symlink(path, link)
        path = link

    buffer = bytearray()

    def readable() -> None:
        try:
            data = os.read(master, 1024)
        except (BlockingIOError, OSError):
            return
        buffer.extend(data)
        for packet in split_packets(buffer):
            sim.process(packet, lambda reply: os.write(master, reply))

    asyncio.get_running_loop().add_reader(master, readable)
    serve_pty.keep_open = slave  # keep the slave fd open so the pty survives client reconnects
    return path
