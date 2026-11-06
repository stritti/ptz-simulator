# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""VISCA command interpreter.

Takes raw VISCA packets (``8x ... FF``), applies them to a :class:`CameraState`
and produces the replies a real camera would send.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, FrozenSet, List, Optional

from . import state as st
from .state import CameraState

TERMINATOR = 0xFF
# Sony cameras have two command buffers ("sockets", Sony VISCA Command List, "Socket").
SOCKETS = (1, 2)
SOCKET = SOCKETS[0]
PAN_TILT = frozenset(("pan", "tilt"))
ALL_AXES = frozenset(("pan", "tilt", "zoom", "focus"))

VENDOR_ID = 0x0001  # Sony
MODEL_ID = 0x0519
ROM_VERSION = 0x0100

# VISCA white balance modes per docs/visca-interface-api-description (AXIS example).
WB_VISCA_MODES = {0x00: "auto", 0x01: "indoor", 0x02: "outdoor", 0x04: "auto_outdoor", 0x05: "manual"}
WB_VISCA_CODES = {mode: code for code, mode in WB_VISCA_MODES.items()}
# Preset speed select (Sony list, command category 7E).
PRESET_SPEED_MODES = {0x01: "separate", 0x02: "common"}
PRESET_SPEED_CODES = {mode: code for code, mode in PRESET_SPEED_MODES.items()}


class ViscaError(Exception):
    """Raised by a command handler; carries the VISCA error code."""

    MESSAGE_LENGTH = 0x01
    SYNTAX = 0x02
    BUFFER_FULL = 0x03
    CANCELLED = 0x04
    NO_SOCKET = 0x05
    NOT_EXECUTABLE = 0x41

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Reply:
    data: bytes
    # When True the reply must only be sent once ``axes`` have finished moving.
    after_motion: bool = False
    # Socket the waiting completion belongs to, and the axes it waits for.
    socket: Optional[int] = None
    axes: FrozenSet[str] = ALL_AXES
    # Set for a successful cancel: the waiting completion of this socket is dropped.
    cancel_socket: Optional[int] = None
    # Set for IF_Clear: every waiting completion is dropped.
    clear_buffers: bool = False


@dataclass
class LogEntry:
    raw: bytes
    description: str
    ok: bool
    # Shown instead of the hex dump for non-VISCA protocols (e.g. "ONVIF").
    label: str = ""

    @property
    def source(self) -> str:
        return self.label or hexdump(self.raw)


def hexdump(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def parse_hex(text: str) -> bytes:
    return bytes.fromhex(text.replace(",", " ").replace("0x", ""))


def decode_nibbles(data: bytes, signed: bool = False) -> int:
    value = 0
    for b in data:
        value = (value << 4) | (b & 0x0F)
    bits = 4 * len(data)
    if signed and value & (1 << (bits - 1)):
        value -= 1 << bits
    return value


def encode_nibbles(value: int, count: int = 4) -> bytes:
    value &= (1 << (4 * count)) - 1
    return bytes((value >> (4 * (count - 1 - i))) & 0x0F for i in range(count))


def split_packets(buffer: bytearray) -> List[bytes]:
    """Remove and return every complete VISCA packet from a stream buffer."""
    packets = []
    while True:
        try:
            end = buffer.index(TERMINATOR)
        except ValueError:
            return packets
        packet = bytes(buffer[: end + 1])
        del buffer[: end + 1]
        if len(packet) > 1:
            packets.append(packet)


class ViscaCamera:
    """A single VISCA device at ``address`` (1..7)."""

    def __init__(self, camera: Optional[CameraState] = None, address: int = 1, instant: bool = False):
        self.state = camera or CameraState()
        self.address = address
        self.instant = instant
        self.log: Deque[LogEntry] = deque(maxlen=200)
        self.command_count = 0
        self._pan_tilt_instructed = False  # for the "operation complete" status bits
        # Busy command sockets and the axes their completion waits for.
        self.sockets: Dict[int, FrozenSet[str]] = {}
        self._socket = SOCKET  # socket of the command being handled

    # ---------------------------------------------------------------- replies
    @property
    def _reply_header(self) -> int:
        return (self.address + 8) << 4  # camera 1 answers with 0x90

    def _ack(self, socket: int) -> bytes:
        return bytes([self._reply_header, 0x40 | socket, TERMINATOR])

    def _completion(self, socket: int) -> bytes:
        return bytes([self._reply_header, 0x50 | socket, TERMINATOR])

    def _inquiry_reply(self, payload: bytes) -> bytes:
        return bytes([self._reply_header, 0x50]) + payload + bytes([TERMINATOR])

    def _error(self, code: int, socket: int = SOCKET) -> bytes:
        # Message length, syntax error and buffer full always carry socket 0.
        if code in (ViscaError.MESSAGE_LENGTH, ViscaError.SYNTAX, ViscaError.BUFFER_FULL):
            socket = 0
        return bytes([self._reply_header, 0x60 | socket, code, TERMINATOR])

    def _free_socket(self) -> Optional[int]:
        """Lowest free command socket; sockets whose motion has finished are freed first."""
        for socket, axes in list(self.sockets.items()):
            if not self.state.axes_busy(axes):
                del self.sockets[socket]
        return next((n for n in SOCKETS if n not in self.sockets), None)

    # ----------------------------------------------------------------- entry
    def handle(self, packet: bytes) -> List[Reply]:
        """Process one VISCA packet and return the replies to send."""
        self.command_count += 1
        self._socket = SOCKET
        if len(packet) < 3 or packet[-1] != TERMINATOR or not packet[0] & 0x80:
            self._log(packet, "invalid packet", ok=False)
            return [Reply(self._error(ViscaError.SYNTAX))]

        header = packet[0]
        if header == 0x88:
            return self._broadcast(packet)
        target = header & 0x0F
        if target != self.address:
            self._log(packet, f"ignored (addressed to camera {target})", ok=True)
            return []

        body = packet[1:-1]
        try:
            if body[0] == 0x01:
                return self._command(packet, body[1:])
            if body[0] == 0x09:
                return self._inquiry(packet, body[1:])
            if body[0] & 0xF0 == 0x20 and len(body) == 1:
                return self._cancel(packet, body[0] & 0x0F)
            raise ViscaError(ViscaError.SYNTAX, "unknown message type")
        except ViscaError as err:
            self._log(packet, f"error: {err}", ok=False)
            return [Reply(self._error(err.code, self._socket))]
        except IndexError:
            self._log(packet, "error: truncated packet", ok=False)
            return [Reply(self._error(ViscaError.SYNTAX))]

    def record(self, label: str, description: str, ok: bool = True) -> None:
        """Log a command that arrived over another protocol (e.g. ONVIF)."""
        self.command_count += 1
        self.log.append(LogEntry(b"", description, ok, label))

    def _log(self, raw: bytes, description: str, ok: bool = True) -> None:
        self.log.append(LogEntry(raw, description, ok))

    def _cancel(self, packet: bytes, socket: int) -> List[Reply]:
        """Command cancel ``8x 2z FF``: stop the command waiting in socket z."""
        self._free_socket()
        axes = self.sockets.pop(socket, None)
        if axes is None:
            self._log(packet, f"command cancel: no command in socket {socket}", ok=False)
            return [Reply(self._error(ViscaError.NO_SOCKET, socket))]
        self.state.stop_axes(axes)
        self._log(packet, f"command cancel (socket {socket})")
        return [Reply(self._error(ViscaError.CANCELLED, socket), cancel_socket=socket)]

    def _clear_buffers(self) -> None:
        self.state.stop_all()
        self.sockets.clear()

    # -------------------------------------------------------------- broadcast
    def _broadcast(self, packet: bytes) -> List[Reply]:
        if len(packet) == 4 and packet[1] == 0x30 and 1 <= packet[2] <= 7:
            # Address set: take the address and pass the next one down the chain.
            self.address = packet[2]
            self._log(packet, f"address set (broadcast): camera {self.address}")
            return [Reply(bytes([0x88, 0x30, self.address + 1, TERMINATOR]))]
        if packet[1:4] == b"\x01\x00\x01":
            self._clear_buffers()
            self._log(packet, "IF_Clear (broadcast)")
            return [Reply(bytes([0x88, 0x01, 0x00, 0x01, TERMINATOR]), clear_buffers=True)]
        self._log(packet, "unknown broadcast", ok=False)
        return [Reply(self._error(ViscaError.SYNTAX))]

    # --------------------------------------------------------------- commands
    def _command(self, packet: bytes, body: bytes) -> List[Reply]:
        category, cmd, args = body[0], body[1], body[2:]
        s = self.state

        if category == 0x00 and cmd == 0x01 and not args:
            self._clear_buffers()
            self._log(packet, "IF_Clear")
            # Sony VISCA Command List: no ACK, completion with socket 0
            return [Reply(bytes([self._reply_header, 0x50, TERMINATOR]), clear_buffers=True)]

        socket = self._free_socket()
        if socket is None:
            raise ViscaError(ViscaError.BUFFER_FULL, "both command sockets are busy")
        self._socket = socket

        if category == 0x04 and cmd == 0x00:
            on = self._choice(args, {0x02: True, 0x03: False})
            s.power = on
            if not on:
                s.stop_all()
            self._log(packet, f"power {'on' if on else 'standby'}")
            return self._done()

        if not s.power:
            raise ViscaError(ViscaError.NOT_EXECUTABLE, "camera in standby")

        if category == 0x04:
            return self._camera_command(packet, cmd, args)
        if category == 0x7E:
            return self._preset_speed_command(packet, cmd, args)
        if category == 0x06:
            return self._pan_tilt_command(packet, cmd, args)
        raise ViscaError(ViscaError.SYNTAX, f"unknown command category {category:02X}")

    def _camera_command(self, packet: bytes, cmd: int, args: bytes) -> List[Reply]:
        s = self.state
        if cmd == 0x07:  # Zoom
            self._expect_len(args, 1)
            arg = args[0]
            if arg == 0x00:
                s.drive_zoom(0, 0)
                self._log(packet, "zoom stop")
            elif arg in (0x02, 0x03):
                s.drive_zoom(1 if arg == 0x02 else -1, 3)
                self._log(packet, f"zoom {'tele' if arg == 0x02 else 'wide'} (standard)")
            elif arg >> 4 in (0x2, 0x3) and arg & 0x0F <= 7:
                direction = 1 if arg >> 4 == 0x2 else -1
                s.drive_zoom(direction, arg & 0x0F)
                self._log(packet, f"zoom {'tele' if direction > 0 else 'wide'} speed {arg & 0x0F}")
            else:
                raise ViscaError(ViscaError.SYNTAX, "bad zoom argument")
            return self._done()

        if cmd == 0x47:  # Zoom direct
            self._expect_len(args, 4)
            value = decode_nibbles(args)
            s.zoom_to(value)
            self._log(packet, f"zoom direct {value:#06x}")
            return self._done(after_motion=True, axes=frozenset(("zoom",)))

        if cmd == 0x08:  # Focus
            self._expect_len(args, 1)
            arg = args[0]
            if arg != 0x00:
                self._manual_focus_only()
            if arg == 0x00:
                s.drive_focus(0, 0)
                self._log(packet, "focus stop")
            elif arg in (0x02, 0x03):
                s.drive_focus(-1 if arg == 0x02 else 1, 3)
                self._log(packet, f"focus {'far' if arg == 0x02 else 'near'} (standard)")
            elif arg >> 4 in (0x2, 0x3) and arg & 0x0F <= 7:
                direction = -1 if arg >> 4 == 0x2 else 1
                s.drive_focus(direction, arg & 0x0F)
                self._log(packet, f"focus {'far' if direction < 0 else 'near'} speed {arg & 0x0F}")
            else:
                raise ViscaError(ViscaError.SYNTAX, "bad focus argument")
            return self._done()

        if cmd == 0x48:  # Focus direct
            self._expect_len(args, 4)
            self._manual_focus_only()
            value = decode_nibbles(args)
            s.focus_to(value)
            self._log(packet, f"focus direct {value:#06x}")
            return self._done(after_motion=True, axes=frozenset(("focus",)))

        if cmd == 0x38:  # Focus mode
            arg = self._choice(args, {0x02: "auto", 0x03: "manual", 0x10: "toggle"})
            s.autofocus = (not s.autofocus) if arg == "toggle" else arg == "auto"
            self._log(packet, f"focus mode {'auto' if s.autofocus else 'manual'}")
            return self._done()

        if cmd == 0x18 and args == b"\x01":  # One push AF
            self._log(packet, "one push AF")
            return self._done()

        if cmd == 0x35:  # White balance mode
            self._expect_len(args, 1)
            s.set_white_balance(self._choice(args, WB_VISCA_MODES))
            self._log(packet, f"white balance {s.white_balance}")
            return self._done()

        if cmd in (0x03, 0x04, 0x43, 0x44):  # Relative (03/04) and absolute (43/44) red/blue gain
            red = cmd in (0x03, 0x43)
            current = s.red_gain if red else s.blue_gain
            if cmd in (0x03, 0x04):
                self._expect_len(args, 1)
                value = {0x00: st.WB_GAIN_NEUTRAL, 0x02: current + st.WB_GAIN_STEP,
                         0x03: current - st.WB_GAIN_STEP}.get(args[0])
                if value is None:
                    raise ViscaError(ViscaError.SYNTAX, "bad gain argument")
            else:
                self._expect_len(args, 4)
                value = decode_nibbles(args)
                if value > st.WB_GAIN_MAX:
                    raise ViscaError(ViscaError.SYNTAX, "gain out of range")
            if red:
                s.set_gains(value, s.blue_gain)
            else:
                s.set_gains(s.red_gain, value)
            gain = s.red_gain if red else s.blue_gain
            self._log(packet, f"{'red' if red else 'blue'} gain {gain:#04x}")
            return self._done()

        if cmd == 0x10 and args == b"\x05":  # WB SET (one push)
            s.one_push_white_balance()
            self._log(packet, "one push white balance")
            return self._done()

        if cmd == 0x3F:  # Memory (presets)
            self._expect_len(args, 2)
            action, number = args
            if number >= st.PRESET_COUNT:
                raise ViscaError(ViscaError.SYNTAX, f"preset {number} out of range")
            if action == 0x00:
                s.clear_preset(number)
                self._log(packet, f"preset {number + 1} reset")
                return self._done()
            if action == 0x01:
                s.save_preset(number)
                self._log(packet, f"preset {number + 1} set")
                return self._done()
            if action == 0x02:
                if not s.recall_preset(number):
                    raise ViscaError(ViscaError.NOT_EXECUTABLE, f"preset {number + 1} not set")
                self._log(packet, f"preset {number + 1} recall")
                return self._done(after_motion=True)
            raise ViscaError(ViscaError.SYNTAX, "bad memory action")

        raise ViscaError(ViscaError.SYNTAX, f"unsupported camera command {cmd:02X}")

    def _preset_speed_command(self, packet: bytes, cmd: int, args: bytes) -> List[Reply]:
        s = self.state
        if cmd == 0x04 and args[:1] == b"\x1B":  # Speed select: separate or common
            self._expect_len(args, 2)
            s.preset_speed_mode = self._choice(args[1:], PRESET_SPEED_MODES)
            self._log(packet, f"preset speed {s.preset_speed_mode}")
            return self._done()
        if cmd == 0x04 and args[:1] == b"\x1C":  # Common speed
            self._expect_len(args, 3)
            s.common_preset_speed = self._preset_speed(decode_nibbles(args[1:]))
            self._log(packet, f"common preset speed {s.common_preset_speed}")
            return self._done()
        if cmd == 0x01 and args[:1] == b"\x0B":  # Separate speed for one preset
            self._expect_len(args, 3)
            number = args[1]
            if number >= st.PRESET_COUNT:
                raise ViscaError(ViscaError.SYNTAX, f"preset {number + 1} out of range")
            s.preset_speeds[number] = self._preset_speed(args[2])
            self._log(packet, f"preset {number + 1} speed {s.preset_speeds[number]}")
            return self._done()
        raise ViscaError(ViscaError.SYNTAX, f"unsupported extended command {cmd:02X}")

    @staticmethod
    def _preset_speed(value: int) -> int:
        if not 1 <= value <= st.PRESET_SPEED_MAX:
            raise ViscaError(ViscaError.SYNTAX, "preset speed out of range")
        return value

    def _pan_tilt_command(self, packet: bytes, cmd: int, args: bytes) -> List[Reply]:
        s = self.state
        self._pan_tilt_instructed = True
        if cmd == 0x01:  # Pan-tilt drive
            self._expect_len(args, 4)
            pan_speed, tilt_speed = self._speeds(args[0], args[1])
            pan_dir = {0x01: -1, 0x02: 1, 0x03: 0}.get(args[2])
            tilt_dir = {0x01: 1, 0x02: -1, 0x03: 0}.get(args[3])
            if pan_dir is None or tilt_dir is None:
                raise ViscaError(ViscaError.SYNTAX, "bad pan/tilt direction")
            s.drive_pan_tilt(pan_dir, tilt_dir, pan_speed, tilt_speed)
            names = {(-1, 0): "left", (1, 0): "right", (0, 1): "up", (0, -1): "down",
                     (-1, 1): "up-left", (1, 1): "up-right", (-1, -1): "down-left",
                     (1, -1): "down-right", (0, 0): "stop"}
            self._log(packet, f"pan/tilt {names[(pan_dir, tilt_dir)]} "
                              f"(speed {pan_speed}/{tilt_speed})")
            return self._done()

        if cmd in (0x02, 0x03):  # Absolute / relative position
            # 4 nibbles per axis (BRC/EVI, Axis) or 5 (newer Sony, e.g. ILME-FR7)
            if len(args) not in (10, 12):
                raise ViscaError(ViscaError.SYNTAX, f"expected 10 or 12 argument bytes, got {len(args)}")
            digits = (len(args) - 2) // 2
            if args[1] == 0x00:  # tilt speed 00: "synced with pan operation"
                pan_speed, _ = self._speeds(args[0], 1)
                tilt_speed = max(1, round(pan_speed * st.TILT_SPEED_MAX / st.PAN_SPEED_MAX))
            else:
                pan_speed, tilt_speed = self._speeds(args[0], args[1])
            pan = decode_nibbles(args[2:2 + digits], signed=True)
            tilt = decode_nibbles(args[2 + digits:], signed=True)
            if cmd == 0x02:
                s.move_pan_tilt_to(pan, tilt, pan_speed, tilt_speed)
                self._log(packet, f"absolute pan {pan} tilt {tilt}")
            else:
                base_pan = s.pan_target[0] if s.pan_target else s.pan
                base_tilt = s.tilt_target[0] if s.tilt_target else s.tilt
                s.move_pan_tilt_to(base_pan + pan, base_tilt + tilt, pan_speed, tilt_speed)
                self._log(packet, f"relative pan {pan:+d} tilt {tilt:+d}")
            return self._done(after_motion=True, axes=PAN_TILT)

        if cmd == 0x04 and not args:
            s.home()
            self._log(packet, "home")
            return self._done(after_motion=True, axes=PAN_TILT)

        if cmd == 0x05 and not args:
            s.stop_pan_tilt()
            self._log(packet, "pan/tilt driver reset")
            return self._done()

        raise ViscaError(ViscaError.SYNTAX, f"unsupported pan/tilt command {cmd:02X}")

    # -------------------------------------------------------------- inquiries
    def _inquiry(self, packet: bytes, body: bytes) -> List[Reply]:
        s = self.state
        pan, tilt, zoom, focus = s.position()
        key = bytes(body)
        if key == b"\x04\x00":
            payload, what = bytes([0x02 if s.power else 0x03]), "power"
        elif key == b"\x04\x47":
            payload, what = encode_nibbles(zoom), "zoom position"
        elif key == b"\x04\x48":
            payload, what = encode_nibbles(focus), "focus position"
        elif key == b"\x04\x38":
            payload, what = bytes([0x02 if s.autofocus else 0x03]), "focus mode"
        elif key == b"\x04\x35":
            payload, what = bytes([WB_VISCA_CODES[s.white_balance]]), "white balance mode"
        elif key == b"\x7e\x04\x1b":
            payload, what = bytes([PRESET_SPEED_CODES[s.preset_speed_mode]]), "preset speed mode"
        elif key == b"\x7e\x04\x1c":
            payload, what = encode_nibbles(s.common_preset_speed, count=2), "common preset speed"
        elif len(key) == 4 and key[:3] == b"\x7e\x01\x0b":
            if key[3] >= st.PRESET_COUNT:
                raise ViscaError(ViscaError.SYNTAX, f"preset {key[3]} out of range")
            payload = bytes([s.preset_speeds.get(key[3], st.PRESET_SPEED_DEFAULT)])
            what = "preset speed"
        elif key == b"\x06\x12":
            payload, what = encode_nibbles(pan) + encode_nibbles(tilt), "pan/tilt position"
        elif key == b"\x06\x11":
            payload, what = bytes([st.PAN_SPEED_MAX, st.TILT_SPEED_MAX]), "max speed"
        elif key == b"\x06\x10":
            payload, what = self._pan_tilt_status(), "pan/tilt status"
        elif key == b"\x00\x02":
            payload = (VENDOR_ID.to_bytes(2, "big") + MODEL_ID.to_bytes(2, "big")
                       + ROM_VERSION.to_bytes(2, "big") + bytes([0x02]))
            what = "version"
        else:
            raise ViscaError(ViscaError.SYNTAX, f"unsupported inquiry {hexdump(key)}")
        self._log(packet, f"inquiry {what}")
        return [Reply(self._inquiry_reply(payload))]

    def _pan_tilt_status(self) -> bytes:
        """Sony "Pan/Tilt Status Codes": initialized, operating/complete, limit bits."""
        s = self.state
        status = 0x2000  # initialization completes
        moving = (s.pan_velocity or s.tilt_velocity or s.pan_target is not None
                  or s.tilt_target is not None)
        if moving:
            status |= 0x0400  # pan/tilt operating
        elif self._pan_tilt_instructed:
            status |= 0x0800  # pan/tilt operations complete
        if s.pan <= st.PAN_MIN:
            status |= 0x0001
        if s.pan >= st.PAN_MAX:
            status |= 0x0002
        if s.tilt >= st.TILT_MAX:
            status |= 0x0004
        if s.tilt <= st.TILT_MIN:
            status |= 0x0008
        return status.to_bytes(2, "big")

    # ---------------------------------------------------------------- helpers
    def _done(self, after_motion: bool = False, axes: FrozenSet[str] = ALL_AXES) -> List[Reply]:
        """ACK and completion for the current socket; absolute moves complete later."""
        socket = self._socket
        if after_motion and self.instant:
            self.state.finish_moves()
        wait = after_motion and not self.instant and self.state.axes_busy(axes)
        if wait:
            self.sockets[socket] = axes
        return [Reply(self._ack(socket)),
                Reply(self._completion(socket), after_motion=wait, socket=socket, axes=axes)]

    def _manual_focus_only(self) -> None:
        # Sony VISCA Command List: manual focus during auto focus is "not executable".
        if self.state.autofocus:
            raise ViscaError(ViscaError.NOT_EXECUTABLE, "manual focus while auto focus is on")

    @staticmethod
    def _expect_len(args: bytes, length: int) -> None:
        if len(args) != length:
            raise ViscaError(ViscaError.SYNTAX, f"expected {length} argument bytes, got {len(args)}")

    @staticmethod
    def _choice(args: bytes, options: dict):
        if len(args) != 1 or args[0] not in options:
            raise ViscaError(ViscaError.SYNTAX, "bad argument")
        return options[args[0]]

    @staticmethod
    def _speeds(pan_speed: int, tilt_speed: int):
        if not 1 <= pan_speed <= st.PAN_SPEED_MAX or not 1 <= tilt_speed <= st.TILT_SPEED_MAX:
            raise ViscaError(ViscaError.SYNTAX, "speed out of range")
        return pan_speed, tilt_speed
