# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Pelco-D command interpreter (serial RS-485 protocol).

Takes 7-byte Pelco-D frames (``FF addr cmd1 cmd2 data1 data2 checksum``), applies
them to the shared :class:`~ptzsim.state.CameraState` and produces the 4-byte
general response a real camera sends back. See the Pelco "D" Protocol manual
(revision 5.x, sections 3 and 4) and the Fujifilm SX400 Pelco-D specification
v1.10.0 (linked in README.md): send format 3.1, general response 3.2.1, runaway
timeout 4, standard command 5.1, Set Zoom/Focus Speed 5.2.1/5.2.2.
"""

from __future__ import annotations

import asyncio
from typing import Callable, List, Optional

from . import state as st
from .state import CameraState
from .visca import ViscaCamera, hexdump

SYNC = 0xFF
FRAME_LEN = 7

# Command 2 bitmask for motion commands (bit 0 of cmd2 is always 0 there; when
# set, cmd2 carries an extended-command opcode instead, Pelco manual 3.1.1).
PAN_RIGHT = 0x02
PAN_LEFT = 0x04
TILT_UP = 0x08
TILT_DOWN = 0x10
ZOOM_TELE = 0x20
ZOOM_WIDE = 0x40
FOCUS_FAR = 0x80

# Command 1 bits 0..2: focus near, iris open, iris close (standard command, 5.1.1).
# Bits 3..7 (camera on/off, auto/manual scan, sense) are not used by the current
# Pelco-D and are not supported (5.1.1 note 1).
FOCUS_NEAR_CMD1 = 0x01
IRIS_OPEN_CMD1 = 0x02
IRIS_CLOSE_CMD1 = 0x04
STANDARD_CMD1 = FOCUS_NEAR_CMD1 | IRIS_OPEN_CMD1 | IRIS_CLOSE_CMD1

# Extended-command opcodes in command 2 (bit 0 set), preset number in data 2.
CMD2_SET_PRESET = 0x03
CMD2_CLEAR_PRESET = 0x05
CMD2_CALL_PRESET = 0x07
PRESET_OPCODES = {CMD2_SET_PRESET: "set", CMD2_CLEAR_PRESET: "clear", CMD2_CALL_PRESET: "call"}
CMD2_SET_ZOOM_SPEED = 0x25  # data 2: 0x00 slowest .. 0x03 highest (5.2.1)
CMD2_SET_FOCUS_SPEED = 0x27  # data 2: 0x00 slowest .. 0x03 highest (5.2.2)

SPEED_MAX = 0x3F  # data field range 0x00..0x3F
TURBO = 0xFF  # turbo speed: maximum the device can go
ALARMS = 0x00  # alarm byte of the general response: no alarm (3.2.1)
# Standard commands stop by themselves after this many seconds (runaway detection,
# section 4); a new drive command restarts the timer.
RUNAWAY_TIMEOUT = 15.0
# Set Zoom/Focus Speed 0x00..0x03 onto the VISCA speeds 0..7; other values fall
# back to "low medium" (zoom) / "high medium" (focus) like the SX400 (5.2.1, 5.2.2).
ZOOM_SPEEDS = {0x00: 0, 0x01: 2, 0x02: 5, 0x03: 7}
FOCUS_SPEEDS = ZOOM_SPEEDS
ZOOM_SPEED_FALLBACK, FOCUS_SPEED_FALLBACK = 0x01, 0x02
ZOOM_SPEED_DEFAULT = 0x03  # the spec names no factory default: highest speed
FOCUS_SPEED_DEFAULT = 0x02
# Contradicting direction bits make a standard command invalid (5.1.1 note 4).
CONTRADICTIONS = ((0, PAN_LEFT | PAN_RIGHT), (0, TILT_UP | TILT_DOWN), (0, ZOOM_TELE | ZOOM_WIDE),
                  (FOCUS_NEAR_CMD1, FOCUS_FAR), (IRIS_OPEN_CMD1 | IRIS_CLOSE_CMD1, 0))

Send = Callable[[bytes], None]


def checksum(frame: bytes) -> int:
    """Sum of bytes 2..6 (address .. data 2) modulo 256."""
    return sum(frame[1:6]) & 0xFF


def split_frames(buffer: bytearray) -> List[bytes]:
    """Remove and return every complete, checksum-valid 7-byte frame.

    Resyncs on the sync byte: garbage before it is dropped, and a 7-byte
    candidate with a wrong checksum is discarded byte by byte (only its sync
    byte), so a stray ``0xFF`` cannot swallow a following valid frame.
    """
    frames = []
    while True:
        try:
            start = buffer.index(SYNC)
        except ValueError:
            buffer.clear()  # no sync byte left: all garbage
            return frames
        if start:
            del buffer[:start]  # drop garbage before the sync byte
        if len(buffer) < FRAME_LEN:
            return frames
        candidate = bytes(buffer[:FRAME_LEN])
        if candidate[-1] == checksum(candidate):
            del buffer[:FRAME_LEN]
            frames.append(candidate)
        else:
            del buffer[:1]  # invalid candidate: the next byte may be the real sync


def make_frame(address: int, cmd1: int, cmd2: int, data1: int, data2: int) -> bytes:
    """Build a frame with the checksum appended (helper for clients and tests)."""
    frame = bytes([SYNC, address, cmd1, cmd2, data1, data2])
    return frame + bytes([checksum(frame)])


class PelcoCamera:
    """A single Pelco-D device at ``address`` (1..255) driving the shared camera."""

    def __init__(self, camera: ViscaCamera, address: int = 1):
        self.camera = camera
        self.address = address
        self.zoom_speed = ZOOM_SPEED_DEFAULT  # Set Zoom Speed (0x25) value
        self.focus_speed = FOCUS_SPEED_DEFAULT  # Set Focus Speed (0x27) value
        self._runaway: Optional[asyncio.TimerHandle] = None

    @property
    def state(self) -> CameraState:
        return self.camera.state

    def ack(self, frame: bytes) -> bytes:
        """4-byte general response (3.2.1): sync, address, alarms (0x00), and as
        checksum the request checksum plus the alarm byte, modulo 256."""
        return bytes([SYNC, self.address, ALARMS, (frame[-1] + ALARMS) & 0xFF])

    # ------------------------------------------------------------------ entry
    def process(self, frame: bytes, send: Send) -> None:
        """Handle one frame; send the general response via ``send`` if executed."""
        if len(frame) != FRAME_LEN or frame[0] != SYNC or frame[-1] != checksum(frame):
            self.camera.record("Pelco-D", f"invalid frame {hexdump(frame)}", ok=False)
            return
        if frame[1] != self.address:
            return  # another camera on the bus: stay silent
        reply = self._handle(frame)
        if reply is not None:
            send(reply)

    # --------------------------------------------------------------- commands
    def _handle(self, frame: bytes) -> Optional[bytes]:
        cmd1, cmd2, data1, data2 = frame[2], frame[3], frame[4], frame[5]
        s = self.state
        if not s.power:
            self.camera.record("Pelco-D", "camera in standby, command ignored", ok=False)
            return None

        if cmd1 == 0x00 and cmd2 & 0x01:
            # Extended command: opcode in command 2, argument in data 2.
            if cmd2 in (CMD2_SET_ZOOM_SPEED, CMD2_SET_FOCUS_SPEED):
                return self._set_speed(cmd2, data2, frame)
            return self._preset(cmd2, data2, frame)
        if cmd1 & ~STANDARD_CMD1 & 0xFF or cmd2 & 0x01:
            self.camera.record("Pelco-D", f"unsupported command {cmd1:02X} {cmd2:02X}", ok=False)
            return None
        if any(cmd1 & c1 == c1 and cmd2 & c2 == c2 for c1, c2 in CONTRADICTIONS):
            self.camera.record("Pelco-D", f"contradicting directions {cmd1:02X} {cmd2:02X}, command invalid",
                               ok=False)
            return None
        return self._drive(cmd1, cmd2, data1, data2, frame)

    def _drive(self, cmd1: int, cmd2: int, data1: int, data2: int, frame: bytes) -> bytes:
        """Motion command: the frame describes the whole motion state.

        Cleared direction bits stop their axis; a speed of 0x00 is the slowest
        speed, not a stop (Pelco manual 3.1.2).
        """
        s = self.state
        actions = []
        pan_dir = 1 if cmd2 & PAN_RIGHT else -1 if cmd2 & PAN_LEFT else 0
        tilt_dir = 1 if cmd2 & TILT_UP else -1 if cmd2 & TILT_DOWN else 0
        s.drive_pan_tilt(pan_dir, tilt_dir,
                         self._speed(data1, st.PAN_SPEED_MAX) if pan_dir else 1,
                         self._speed(data2, st.TILT_SPEED_MAX) if tilt_dir else 1)
        if pan_dir:
            actions.append("pan right" if pan_dir > 0 else "pan left")
        if tilt_dir:
            actions.append("tilt up" if tilt_dir > 0 else "tilt down")
        if cmd2 & ZOOM_TELE or cmd2 & ZOOM_WIDE:
            # The zoom speed comes from Set Zoom Speed (0x25), not from data 1,
            # which is the pan speed (5.1.1, 5.2.1).
            direction = 1 if cmd2 & ZOOM_TELE else -1
            s.drive_zoom(direction, ZOOM_SPEEDS.get(self.zoom_speed, ZOOM_SPEEDS[ZOOM_SPEED_FALLBACK]))
            actions.append("zoom tele" if direction > 0 else "zoom wide")
        else:
            s.zoom_velocity = 0.0
            s.zoom_target = None
        if cmd2 & FOCUS_FAR or cmd1 & FOCUS_NEAR_CMD1:
            if s.autofocus:
                self.camera.record("Pelco-D", "focus ignored (autofocus on)", ok=False)
            else:
                direction = -1 if cmd2 & FOCUS_FAR else 1
                s.drive_focus(direction, FOCUS_SPEEDS.get(self.focus_speed, FOCUS_SPEEDS[FOCUS_SPEED_FALLBACK]))
                actions.append("focus far" if direction < 0 else "focus near")
        else:
            s.focus_velocity = 0.0
            s.focus_target = None
        if cmd1 & (IRIS_OPEN_CMD1 | IRIS_CLOSE_CMD1):
            actions.append(f"iris {'open' if cmd1 & IRIS_OPEN_CMD1 else 'close'} (not simulated)")
        self._restart_runaway_timer(bool(pan_dir or tilt_dir or s.zoom_velocity or s.focus_velocity))
        self.camera.record("Pelco-D", ", ".join(actions) if actions else "stop all")
        return self.ack(frame)

    def _restart_runaway_timer(self, moving: bool) -> None:
        """Stop a standard-command motion after RUNAWAY_TIMEOUT seconds (section 4)."""
        if self._runaway is not None:
            self._runaway.cancel()
            self._runaway = None
        if not moving:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no event loop (unit tests): nothing can fire later
        self._runaway = loop.call_later(RUNAWAY_TIMEOUT, self._runaway_stop)

    def _runaway_stop(self) -> None:
        self._runaway = None
        s = self.state
        s.stop_pan_tilt()
        s.zoom_velocity = s.focus_velocity = 0.0
        self.camera.record("Pelco-D", f"no drive command for {RUNAWAY_TIMEOUT:g}s, stopped (runaway detection)")

    def _set_speed(self, opcode: int, value: int, frame: bytes) -> bytes:
        if opcode == CMD2_SET_ZOOM_SPEED:
            self.zoom_speed = value
            self.camera.record("Pelco-D", f"zoom speed {value:02X}")
        else:
            self.focus_speed = value
            self.camera.record("Pelco-D", f"focus speed {value:02X}")
        return self.ack(frame)

    def _preset(self, opcode: int, number: int, frame: bytes) -> Optional[bytes]:
        s = self.state
        action = PRESET_OPCODES.get(opcode)
        if action is None:
            self.camera.record("Pelco-D", f"unsupported extended command 00 {opcode:02X}", ok=False)
            return None
        if number >= st.PRESET_COUNT:
            self.camera.record("Pelco-D", f"preset {number} out of range", ok=False)
            return None
        if action == "set":
            s.save_preset(number)
        elif action == "clear":
            s.clear_preset(number)
        elif not s.recall_preset(number):
            self.camera.record("Pelco-D", f"preset {number + 1} not set", ok=False)
            return None
        if action == "call" and self.camera.instant:
            s.finish_moves()  # --instant: jump to the preset instead of motor speed
        self.camera.record("Pelco-D", f"preset {number + 1} {action}")
        return self.ack(frame)

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _speed(value: int, maximum: int) -> int:
        """Map a Pelco-D speed 0x00..0x3F (0xFF turbo) onto 1..maximum.

        0x00 is the slowest speed, not a stop (Pelco manual 3.1.2).
        """
        if value >= TURBO or value > SPEED_MAX:
            return maximum
        return max(1, round(value * maximum / SPEED_MAX))

