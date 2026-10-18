"""Interactive terminal UI: the live dashboard plus keyboard control of the camera."""

from __future__ import annotations

import asyncio
import time
from typing import Callable, List, Optional

from . import state as st
from .display import render
from .visca import ViscaCamera

SPEED_LEVELS = 8
# Terminals report key presses but no releases, so a jog runs while the key repeats
# and stops this long after the last repeat.
JOG_TIMEOUT = 0.35
SOURCE = "TUI"

PAN_TILT_KEYS = {
    "LEFT": (-1, 0), "RIGHT": (1, 0), "UP": (0, 1), "DOWN": (0, -1),
    "a": (-1, 0), "d": (1, 0), "w": (0, 1), "s": (0, -1),
}
ZOOM_KEYS = {"+": 1, "=": 1, "-": -1}

HELP = [
    "arrows/WASD pan+tilt   +/- zoom   space stop   [ ] speed   h home",
    "1-9 recall preset   P then 1-9 save preset   C then 1-9 clear preset",
    "f autofocus on/off   o power on/standby   q quit",
]


class TuiController:
    """Turns key presses into camera actions. Independent of curses, so it is testable."""

    def __init__(self, camera: ViscaCamera, clock: Callable[[], float] = time.monotonic):
        self.camera = camera
        self.clock = clock
        self.speed = SPEED_LEVELS // 2
        self.pending: Optional[str] = None  # "save" or "clear" while waiting for a digit
        self.message = ""
        self.quit = False
        self._pan_tilt_jog: Optional[tuple] = None
        self._pan_tilt_until = 0.0
        self._zoom_jog: Optional[int] = None
        self._zoom_until = 0.0

    @property
    def state(self) -> st.CameraState:
        return self.camera.state

    # ------------------------------------------------------------------ keys
    def handle_key(self, key: str) -> None:
        if self.pending and key.isdigit() and key != "0":
            self._preset_action(self.pending, int(key))
            self.pending = None
            return
        self.pending = None
        if key in PAN_TILT_KEYS:
            self._jog_pan_tilt(*PAN_TILT_KEYS[key])
        elif key in ZOOM_KEYS:
            self._jog_zoom(ZOOM_KEYS[key])
        elif key == " ":
            self.stop()
        elif key in ("[", "]"):
            step = 1 if key == "]" else -1
            self.speed = int(st.clamp(self.speed + step, 1, SPEED_LEVELS))
            self.message = f"speed {self.speed}/{SPEED_LEVELS}"
        elif key == "h":
            self.state.home()
            self._finish_if_instant()
            self._record("home")
        elif key.isdigit() and key != "0":
            self._preset_action("recall", int(key))
        elif key == "P":
            self.pending, self.message = "save", "save preset: press 1-9"
        elif key == "C":
            self.pending, self.message = "clear", "clear preset: press 1-9"
        elif key == "f":
            self.state.autofocus = not self.state.autofocus
            self._record(f"autofocus {'on' if self.state.autofocus else 'off'}")
        elif key == "o":
            self.state.power = not self.state.power
            if not self.state.power:
                self.state.stop_all()
            self._record(f"power {'on' if self.state.power else 'standby'}")
        elif key in ("q", "Q"):
            self.quit = True

    def tick(self) -> None:
        """Stop jogs whose key is no longer repeating."""
        now = self.clock()
        if self._pan_tilt_jog is not None and now >= self._pan_tilt_until:
            self._pan_tilt_jog = None
            self.state.stop_pan_tilt()
        if self._zoom_jog is not None and now >= self._zoom_until:
            self._zoom_jog = None
            self.state.zoom_velocity = 0.0

    def stop(self) -> None:
        self._pan_tilt_jog = self._zoom_jog = None
        self.state.stop_all()
        self._record("stop")

    # --------------------------------------------------------------- actions
    def _powered(self) -> bool:
        if not self.state.power:
            self.message = "camera is in standby (press o)"
        return self.state.power

    def _jog_pan_tilt(self, pan_dir: int, tilt_dir: int) -> None:
        if not self._powered():
            return
        self._pan_tilt_until = self.clock() + JOG_TIMEOUT
        if self._pan_tilt_jog == (pan_dir, tilt_dir):
            return
        self._pan_tilt_jog = (pan_dir, tilt_dir)
        pan_speed = max(1, round(st.PAN_SPEED_MAX * self.speed / SPEED_LEVELS))
        tilt_speed = max(1, round(st.TILT_SPEED_MAX * self.speed / SPEED_LEVELS))
        self.state.drive_pan_tilt(pan_dir, tilt_dir, pan_speed, tilt_speed)
        direction = {(-1, 0): "left", (1, 0): "right", (0, 1): "up", (0, -1): "down"}
        self._record(f"pan/tilt {direction[(pan_dir, tilt_dir)]} (speed {self.speed})")

    def _jog_zoom(self, direction: int) -> None:
        if not self._powered():
            return
        self._zoom_until = self.clock() + JOG_TIMEOUT
        if self._zoom_jog == direction:
            return
        self._zoom_jog = direction
        self.state.drive_zoom(direction, self.speed - 1)  # VISCA zoom speed 0..7
        self._record(f"zoom {'tele' if direction > 0 else 'wide'} (speed {self.speed})")

    def _preset_action(self, action: str, number: int) -> None:
        if action == "save":
            self.state.save_preset(number)
            self._record(f"save preset {number}")
        elif action == "clear":
            self.state.clear_preset(number)
            self._record(f"clear preset {number}")
        elif self._powered():
            if self.state.recall_preset(number):
                self._finish_if_instant()
                self._record(f"recall preset {number}")
            else:
                self.message = f"preset {number} is empty"

    def _finish_if_instant(self) -> None:
        if self.camera.instant:
            self.state.finish_moves()

    def _record(self, description: str) -> None:
        self.camera.record(SOURCE, description)
        self.message = description

    # ---------------------------------------------------------------- output
    def frame(self, title: str, log_lines: int = 10) -> List[str]:
        lines = render(self.camera, title, color=False, log_lines=log_lines).splitlines()
        if lines and lines[-1].startswith("Ctrl+C"):
            lines.pop()
        status = f"Speed {self.speed}/{SPEED_LEVELS}"
        if self.message:
            status += f"   {self.message}"
        return lines + [status, ""] + HELP


CURSES_KEYS = {"KEY_UP": "UP", "KEY_DOWN": "DOWN", "KEY_LEFT": "LEFT", "KEY_RIGHT": "RIGHT"}


async def interactive(camera: ViscaCamera, title: str, interval: float = 0.05) -> None:
    """Run the interactive UI until the user presses q (needs a terminal with curses)."""
    import curses

    controller = TuiController(camera)
    screen = curses.initscr()
    try:
        curses.noecho()
        curses.cbreak()
        screen.keypad(True)
        screen.nodelay(True)
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        while not controller.quit:
            while True:
                try:
                    key = screen.getkey()
                except curses.error:  # no input pending
                    break
                if key == "\x1b":
                    key = _escape_sequence(screen)
                controller.handle_key(CURSES_KEYS.get(key, key))
            controller.tick()
            _draw(screen, controller.frame(title))
            await asyncio.sleep(interval)
    finally:
        screen.keypad(False)
        curses.nocbreak()
        curses.echo()
        curses.endwin()


ARROW_SEQUENCES = {"[A": "UP", "[B": "DOWN", "[C": "RIGHT", "[D": "LEFT",
                   "OA": "UP", "OB": "DOWN", "OC": "RIGHT", "OD": "LEFT"}


def _escape_sequence(screen) -> str:
    """Arrow keys the terminfo entry does not know arrive as raw ESC [ C / ESC O C."""
    import curses

    sequence = ""
    for _ in range(2):
        try:
            sequence += screen.getkey()
        except curses.error:
            break
    return ARROW_SEQUENCES.get(sequence, "ESC")


def _draw(screen, lines: List[str]) -> None:
    import curses

    height, width = screen.getmaxyx()
    screen.erase()
    for row, line in enumerate(lines[: height - 1]):
        attr = curses.A_BOLD if row == 0 else curses.A_NORMAL
        try:
            screen.addnstr(row, 0, line, width - 1, attr)
        except curses.error:
            pass
    screen.refresh()
