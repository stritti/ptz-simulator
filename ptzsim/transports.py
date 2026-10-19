"""Network / serial transports carrying VISCA to the simulated camera."""

from __future__ import annotations

import asyncio
import logging
import os
import struct
import time
from typing import Callable, List, Optional, Tuple

from .visca import SOCKET, ViscaCamera, hexdump, split_packets

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


class Simulator:
    """Runs the camera physics and routes replies back to the senders."""

    def __init__(self, camera: ViscaCamera, tick_interval: float = 0.02):
        self.camera = camera
        self.tick_interval = tick_interval
        self._pending: List[Tuple[Send, bytes]] = []
        self.clients = 0

    def process(self, packet: bytes, send: Send) -> None:
        log.debug("rx %s", hexdump(packet))
        for reply in self.camera.handle(packet):
            if reply.cancel_socket is not None and self._cancel(reply.cancel_socket):
                self._send(send, self.camera.canceled_reply(reply.cancel_socket))
            elif reply.after_motion and self.camera.state.busy:
                self._pending.append((send, reply.data))
            else:
                self._send(send, reply.data)

    def _send(self, send: Send, data: bytes) -> None:
        log.debug("tx %s", hexdump(data))
        try:
            send(data)
        except (OSError, RuntimeError) as err:  # client went away
            log.debug("send failed: %s", err)

    def _cancel(self, socket: int) -> bool:
        """Drop the completion waiting on ``socket``; False if nothing is running there."""
        if socket != SOCKET or not self._pending:
            return False
        self._pending = []
        self.camera.state.stop_absolute()
        return True

    def step(self, dt: float) -> None:
        self.camera.state.tick(dt)
        if self._pending and not self.camera.state.busy:
            pending, self._pending = self._pending, []
            for send, data in pending:
                self._send(send, data)

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
            self._reply(addr, SONY_CONTROL_REPLY, sequence, b"\x01")
            return
        if payload_type not in (SONY_VISCA_COMMAND, SONY_VISCA_INQUIRY, SONY_VISCA_DEVICE_SETTING):
            log.warning("unknown Sony VISCA-IP payload type %04X from %s", payload_type, addr)
            self._reply(addr, SONY_CONTROL_REPLY, sequence, b"\x0f\x01")
            return

        buffer = bytearray(payload)
        for packet in split_packets(buffer):
            self.sim.process(
                packet,
                lambda reply, a=addr, seq=sequence: self._reply(a, SONY_VISCA_REPLY, seq, reply),
            )


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
