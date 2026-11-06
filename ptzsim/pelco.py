# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Pelco-D command interpreter (serial RS-485 protocol).

Takes 7-byte Pelco-D frames (``FF addr cmd1 cmd2 data1 data2 checksum``), applies
them to the shared :class:`~ptzsim.state.CameraState` and produces the ACK frame a
real camera sends back. See the Pelco "D" Protocol manual and the Fujifilm
SX400/SX1600 specifications (linked in README.md).
"""

from __future__ import annotations

from typing import Callable, List, Optional

from . import state as st
from .state import CameraState
from .visca import ViscaCamera, hexdump

SYNC = 0xFF
FRAME_LEN = 7

# Command 2 bitmask (motion), per the Pelco-D frame layout.
FOCUS_NEAR = 0x01
PAN_RIGHT = 0x02
PAN_LEFT = 0x04
TILT_UP = 0x08
TILT_DOWN = 0x10
ZOOM_TELE = 0x20
ZOOM_WIDE = 0x40
FOCUS_FAR = 0x80

# Command 1 codes.
CMD_DRIVE = 0x00
CMD_SET_PRESET = 0x03
CMD_CLEAR_PRESET = 0x05
CMD_CALL_PRESET = 0x07

ACK_CMD2 = 0xFF  # a command was executed: answer with command 2 = 0xFF

SPEED_MAX = 0x3F  # data field range 0x00..0x3F
TURBO = 0xFF  # turbo speed: maximum the device can go

Send = Callable[[bytes], None]


def checksum(frame: bytes) -> int:
    """Sum of bytes 2..6 (address .. data 2) modulo 256."""
    return sum(frame[1:6]) & 0xFF


def split_frames(buffer: bytearray) -> List[bytes]:
    """Remove and return every complete 7-byte frame, resyncing on the sync byte."""
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
        frame = bytes(buffer[:FRAME_LEN])
        del buffer[:FRAME_LEN]
        frames.append(frame)


def make_frame(address: int, cmd1: int, cmd2: int, data1: int, data2: int) -> bytes:
    """Build a frame with the checksum appended (helper for clients and tests)."""
    frame = bytes([SYNC, address, cmd1, cmd2, data1, data2])
    return frame + bytes([checksum(frame)])


class PelcoCamera:
    """A single Pelco-D device at ``address`` (1..255) driving the shared camera."""

    def __init__(self, camera: ViscaCamera, address: int = 1):
        self.camera = camera
        self.address = address

    @property
    def state(self) -> CameraState:
        return self.camera.state

    def ack(self) -> bytes:
        """The ACK frame: command 2 = 0xFF, no data."""
        return make_frame(self.address, 0x00, ACK_CMD2, 0x00, 0x00)

    # ------------------------------------------------------------------ entry
    def process(self, frame: bytes, send: Send) -> None:
        """Handle one frame; send the ACK via ``send`` if it was executed."""
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

        if cmd1 == CMD_DRIVE:
            return self._drive(cmd2, data1, data2)
        if cmd1 == CMD_SET_PRESET:
            return self._preset("set", data1)
        if cmd1 == CMD_CLEAR_PRESET:
            return self._preset("clear", data1)
        if cmd1 == CMD_CALL_PRESET:
            return self._preset("call", data1)
        self.camera.record("Pelco-D", f"unsupported command {cmd1:02X}", ok=False)
        return None

    def _drive(self, cmd2: int, data1: int, data2: int) -> Optional[bytes]:
        s = self.state
        if cmd2 == 0x00:
            s.stop_all()
            self.camera.record("Pelco-D", "stop all")
            return self.ack()

        pan_dir = 1 if cmd2 & PAN_RIGHT else -1 if cmd2 & PAN_LEFT else 0
        tilt_dir = 1 if cmd2 & TILT_UP else -1 if cmd2 & TILT_DOWN else 0
        if pan_dir and data1 == 0x00:
            pan_dir = 0  # speed 0 means stop
        if tilt_dir and data2 == 0x00:
            tilt_dir = 0
        actions = []
        if pan_dir or tilt_dir:
            pan_speed = self._speed(data1, st.PAN_SPEED_MAX) if pan_dir else 1
            tilt_speed = self._speed(data2, st.TILT_SPEED_MAX) if tilt_dir else 1
            s.drive_pan_tilt(pan_dir, tilt_dir, pan_speed, tilt_speed)
            if pan_dir:
                actions.append("pan right" if pan_dir > 0 else "pan left")
            if tilt_dir:
                actions.append("tilt up" if tilt_dir > 0 else "tilt down")
        if cmd2 & ZOOM_TELE or cmd2 & ZOOM_WIDE:
            direction = 1 if cmd2 & ZOOM_TELE else -1
            s.drive_zoom(direction, self._zoom_speed(data1))
            actions.append("zoom tele" if direction > 0 else "zoom wide")
        if cmd2 & FOCUS_FAR or cmd2 & FOCUS_NEAR:
            if s.autofocus:
                self.camera.record("Pelco-D", "focus ignored (autofocus on)", ok=False)
            else:
                direction = -1 if cmd2 & FOCUS_FAR else 1
                s.drive_focus(direction, 3)
                actions.append("focus far" if direction < 0 else "focus near")
        self.camera.record("Pelco-D", ", ".join(actions) if actions else f"drive {cmd2:02X}")
        return self.ack()

    def _preset(self, action: str, number: int) -> Optional[bytes]:
        s = self.state
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
        self.camera.record("Pelco-D", f"preset {number + 1} {action}")
        return self.ack()

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _speed(value: int, maximum: int) -> int:
        """Map a Pelco-D speed 0x00..0x3F (0xFF turbo) onto 1..maximum."""
        if value >= TURBO or value > SPEED_MAX:
            return maximum
        return max(1, round(value * maximum / SPEED_MAX))

    @staticmethod
    def _zoom_speed(value: int) -> int:
        """Map a Pelco-D speed onto the VISCA zoom speed 0..7."""
        if value >= TURBO or value > SPEED_MAX:
            return 7
        return round(value * 7 / SPEED_MAX)
