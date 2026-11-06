# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Simulated camera state: position, motion and presets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

# Position limits in VISCA units (modelled on common Sony / PTZOptics cameras).
PAN_MIN, PAN_MAX = -2448, 2448  # 0xF670 .. 0x0990, approx. +-170 deg
TILT_MIN, TILT_MAX = -432, 1296  # 0xFE50 .. 0x0510, approx. -30 .. +90 deg
ZOOM_MIN, ZOOM_MAX = 0x0000, 0x4000  # wide .. tele
FOCUS_MIN, FOCUS_MAX = 0x1000, 0xF000  # infinity .. near

UNITS_PER_DEGREE = 14.4
MAX_OPTICAL_ZOOM = 20.0

PAN_SPEED_MAX = 0x18
TILT_SPEED_MAX = 0x17

# How fast the simulated motors move.
PAN_TILT_UNITS_PER_SPEED_STEP = 60.0  # units/s per speed step
ZOOM_UNITS_PER_SPEED_STEP = 1600.0  # units/s per zoom speed step (p = 0..7)
FOCUS_UNITS_PER_SPEED_STEP = 4000.0

PRESET_COUNT = 64  # VISCA preset numbers 00..63 (Sony list), shown as 1..64
# Preset drive speed 01..32 hex (1..50 in the Sony list); the doc gives no factory default.
PRESET_SPEED_MAX = 50
PRESET_SPEED_DEFAULT = PRESET_SPEED_MAX

# White balance (VISCA API doc): gains 0x00..0xFF, 0x80 is 50 %.
WB_MODES = ("auto", "indoor", "outdoor", "auto_outdoor", "manual")
WB_AUTO_MODES = ("auto", "auto_outdoor")
WB_GAIN_NEUTRAL, WB_GAIN_MAX = 0x80, 0xFF
WB_GAIN_STEP = 8  # simulator choice: the doc does not give the relative step


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _approach(current: float, target: float, step: float) -> float:
    if abs(target - current) <= step:
        return target
    return current + step if target > current else current - step


@dataclass
class Preset:
    pan: int
    tilt: int
    zoom: int
    focus: int
    name: Optional[str] = None


@dataclass
class CameraState:
    power: bool = True
    pan: float = 0.0
    tilt: float = 0.0
    zoom: float = 0.0
    focus: float = 0x8000
    autofocus: bool = True

    # Continuous motion in units per second (signed).
    pan_velocity: float = 0.0
    tilt_velocity: float = 0.0
    zoom_velocity: float = 0.0
    focus_velocity: float = 0.0

    # Targets for absolute moves; (target, units per second).
    pan_target: Optional[Tuple[float, float]] = None
    tilt_target: Optional[Tuple[float, float]] = None
    zoom_target: Optional[Tuple[float, float]] = None
    focus_target: Optional[Tuple[float, float]] = None

    presets: Dict[int, Preset] = field(default_factory=dict)
    last_preset: Optional[int] = None
    home_position: Tuple[float, float] = (0.0, 0.0)

    preset_speed_mode: str = "separate"  # "separate" or "common"
    preset_speeds: Dict[int, int] = field(default_factory=dict)
    common_preset_speed: int = PRESET_SPEED_DEFAULT

    white_balance: str = "auto"
    red_gain: int = WB_GAIN_NEUTRAL
    blue_gain: int = WB_GAIN_NEUTRAL

    # ----------------------------------------------------------------- queries
    @property
    def busy(self) -> bool:
        """True while an absolute move (with a pending completion) is running."""
        return any(
            t is not None
            for t in (self.pan_target, self.tilt_target, self.zoom_target, self.focus_target)
        )

    @property
    def moving(self) -> bool:
        return self.busy or any(
            v != 0.0
            for v in (self.pan_velocity, self.tilt_velocity, self.zoom_velocity, self.focus_velocity)
        )

    @property
    def pan_degrees(self) -> float:
        return self.pan / UNITS_PER_DEGREE

    @property
    def tilt_degrees(self) -> float:
        return self.tilt / UNITS_PER_DEGREE

    @property
    def zoom_ratio(self) -> float:
        return 1.0 + (MAX_OPTICAL_ZOOM - 1.0) * (self.zoom - ZOOM_MIN) / (ZOOM_MAX - ZOOM_MIN)

    def position(self) -> Tuple[int, int, int, int]:
        return round(self.pan), round(self.tilt), round(self.zoom), round(self.focus)

    # ---------------------------------------------------------------- commands
    def stop_pan_tilt(self) -> None:
        self.pan_velocity = self.tilt_velocity = 0.0
        self.pan_target = self.tilt_target = None

    def drive_pan_tilt(self, pan_dir: int, tilt_dir: int, pan_speed: int, tilt_speed: int) -> None:
        """Continuous move. Directions are -1, 0 or +1."""
        self.pan_target = self.tilt_target = None
        self.pan_velocity = pan_dir * pan_speed * PAN_TILT_UNITS_PER_SPEED_STEP
        self.tilt_velocity = tilt_dir * tilt_speed * PAN_TILT_UNITS_PER_SPEED_STEP

    def move_pan_tilt_to(self, pan: float, tilt: float, pan_speed: int, tilt_speed: int) -> None:
        self.pan_velocity = self.tilt_velocity = 0.0
        self.pan_target = (clamp(pan, PAN_MIN, PAN_MAX), pan_speed * PAN_TILT_UNITS_PER_SPEED_STEP)
        self.tilt_target = (clamp(tilt, TILT_MIN, TILT_MAX), tilt_speed * PAN_TILT_UNITS_PER_SPEED_STEP)

    def home(self) -> None:
        self.move_pan_tilt_to(*self.home_position, PAN_SPEED_MAX, TILT_SPEED_MAX)

    def set_home(self) -> None:
        self.home_position = (self.pan, self.tilt)

    def set_white_balance(self, mode: str) -> None:
        self.white_balance = mode

    def set_gains(self, red: int, blue: int) -> None:
        self.red_gain = int(clamp(red, 0, WB_GAIN_MAX))
        self.blue_gain = int(clamp(blue, 0, WB_GAIN_MAX))

    def one_push_white_balance(self) -> None:
        # No colour sensor is simulated: one push locks manual mode at neutral gains.
        self.set_white_balance("manual")
        self.set_gains(WB_GAIN_NEUTRAL, WB_GAIN_NEUTRAL)

    def drive_zoom(self, direction: int, speed: int) -> None:
        self.zoom_target = None
        self.zoom_velocity = direction * (speed + 1) * ZOOM_UNITS_PER_SPEED_STEP

    def zoom_to(self, zoom: float) -> None:
        self.zoom_velocity = 0.0
        self.zoom_target = (clamp(zoom, ZOOM_MIN, ZOOM_MAX), 8 * ZOOM_UNITS_PER_SPEED_STEP)

    def drive_focus(self, direction: int, speed: int) -> None:
        self.focus_target = None
        self.focus_velocity = direction * (speed + 1) * FOCUS_UNITS_PER_SPEED_STEP

    def focus_to(self, focus: float) -> None:
        self.focus_velocity = 0.0
        self.focus_target = (clamp(focus, FOCUS_MIN, FOCUS_MAX), 8 * FOCUS_UNITS_PER_SPEED_STEP)

    def save_preset(self, number: int, name: Optional[str] = None) -> None:
        old = self.presets.get(number)
        if name is None and old is not None:
            name = old.name
        self.presets[number] = Preset(*self.position(), name=name)

    def free_preset_number(self) -> Optional[int]:
        return next((n for n in range(PRESET_COUNT) if n not in self.presets), None)

    def clear_preset(self, number: int) -> None:
        self.presets.pop(number, None)

    def recall_speed(self, number: int) -> float:
        """Preset drive speed as a fraction of the maximum, from the speed settings."""
        if self.preset_speed_mode == "common":
            speed = self.common_preset_speed
        else:
            speed = self.preset_speeds.get(number, PRESET_SPEED_DEFAULT)
        return speed / PRESET_SPEED_MAX

    def recall_preset(self, number: int, speed: Optional[float] = None) -> bool:
        """Start moving to a preset at ``speed`` (0..1 of maximum; default from the speed settings).

        Returns False if the preset is not set.
        """
        preset = self.presets.get(number)
        if preset is None:
            return False
        if speed is None:
            speed = self.recall_speed(number)
        speed = clamp(speed, 0.05, 1.0)
        self.move_pan_tilt_to(preset.pan, preset.tilt, PAN_SPEED_MAX * speed, TILT_SPEED_MAX * speed)
        self.zoom_to(preset.zoom)
        if self.zoom_target is not None:
            self.zoom_target = (self.zoom_target[0], self.zoom_target[1] * speed)
        if not self.autofocus:
            self.focus_to(preset.focus)
        self.last_preset = number
        return True

    def stop_absolute(self) -> None:
        self.pan_target = self.tilt_target = self.zoom_target = self.focus_target = None

    def stop_all(self) -> None:
        self.stop_pan_tilt()
        self.zoom_velocity = self.focus_velocity = 0.0
        self.zoom_target = self.focus_target = None

    def finish_moves(self) -> None:
        """Jump straight to all targets (used in --instant mode and tests)."""
        for name in ("pan", "tilt", "zoom", "focus"):
            target = getattr(self, f"{name}_target")
            if target is not None:
                setattr(self, name, target[0])
                setattr(self, f"{name}_target", None)

    # ---------------------------------------------------------------- physics
    def tick(self, dt: float) -> None:
        """Advance the simulation by dt seconds."""
        self.pan = self._step("pan", self.pan_velocity, dt, PAN_MIN, PAN_MAX)
        self.tilt = self._step("tilt", self.tilt_velocity, dt, TILT_MIN, TILT_MAX)
        self.zoom = self._step("zoom", self.zoom_velocity, dt, ZOOM_MIN, ZOOM_MAX)
        self.focus = self._step("focus", self.focus_velocity, dt, FOCUS_MIN, FOCUS_MAX)

    def _step(self, name: str, velocity: float, dt: float, low: float, high: float) -> float:
        current = getattr(self, name)
        target = getattr(self, f"{name}_target")
        if target is not None:
            goal, speed = target
            current = _approach(current, goal, speed * dt)
            if current == goal:
                setattr(self, f"{name}_target", None)
            return current
        if velocity:
            current = clamp(current + velocity * dt, low, high)
            if current in (low, high):
                setattr(self, f"{name}_velocity", 0.0)
        return current
