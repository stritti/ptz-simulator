# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Interactive terminal UI: the live dashboard plus keyboard control of the camera."""

from __future__ import annotations

import asyncio
import os
import re
import sys
import textwrap
import time
from typing import Callable, List, Optional, Tuple

from . import state as st
from .display import render_camera, render_network
from .viewfinder import CELL_ASPECT, Styles, framed_picture
from .visca import ViscaCamera

ViewBox = Tuple[int, int, int, int]

SPEED_LEVELS = 8
MIN_TERMINAL_COLS, MIN_TERMINAL_ROWS = 120, 8
DASHBOARD_WIDTH = 84  # widest dashboard line (the command log)
MIN_VIEW_COLS, MAX_VIEW_COLS = 30, 90
MIN_VIEW_ROWS = 8
# Terminals report key presses but no releases, so a jog runs while the key repeats
# and stops this long after the last repeat.
JOG_TIMEOUT = 0.35
SOURCE = "TUI"

PAN_TILT_KEYS = {
    "LEFT": (-1, 0), "RIGHT": (1, 0), "UP": (0, 1), "DOWN": (0, -1),
    "a": (-1, 0), "d": (1, 0), "w": (0, 1), "s": (0, -1),
}
ZOOM_KEYS = {"+": 1, "=": 1, "-": -1}

COMMANDS = [
    ("Arrows/WASD", "pan/tilt while held"),
    ("+/-", "zoom tele/wide while held"),
    ("Space", "stop all movement"),
    ("[ / ]", "speed down/up"),
    ("h", "home position"),
    ("1-9", "recall preset"),
    ("P then 1-9", "save preset"),
    ("C then 1-9", "clear preset"),
    ("f", "toggle autofocus"),
    ("b", "one-push white balance"),
    ("o", "power on/standby"),
    ("c / n", "camera / network view"),
    ("PgUp/PgDn", "scroll content"),
    ("? / Esc", "open/close help; cancel preset"),
    ("q", "quit simulator"),
]


class TuiController:
    """Turns key presses into camera actions. Independent of curses, so it is testable."""

    def __init__(self, camera: ViscaCamera, clock: Callable[[], float] = time.monotonic,
                 bind_address: str = "0.0.0.0"):
        self.camera = camera
        self.bind_address = bind_address  # --host, for the network view's client address
        self.clock = clock
        self.speed = SPEED_LEVELS // 2
        self.pending: Optional[str] = None  # "save" or "clear" while waiting for a digit
        self.message = ""
        self.quit = False
        self.current_view = "camera"
        self.help_visible = False
        self.scroll = 0
        self._page_rows = 1
        self._pan_tilt_jog: Optional[tuple] = None
        self._pan_tilt_until = 0.0
        self._zoom_jog: Optional[int] = None
        self._zoom_until = 0.0
        self.view_styles: Styles = []  # colours of the picture from the last layout()

    @property
    def state(self) -> st.CameraState:
        return self.camera.state

    # ------------------------------------------------------------------ keys
    def handle_key(self, key: str) -> None:
        if key == "KEY_RESIZE":
            return
        if key in ("PAGEUP", "PAGEDOWN"):
            step = self._page_rows if key == "PAGEDOWN" else -self._page_rows
            self.scroll = max(0, self.scroll + step)
            return
        if key in ("?", "ESC"):
            if self.pending:
                self.pending = None
                self.message = "preset action cancelled"
            if key == "?" or self.help_visible:
                self.help_visible = not self.help_visible
                self.scroll = 0
            return
        if self.help_visible and key not in ("c", "n", "q", "Q", " "):
            return
        if self.pending and key.isdigit() and key != "0":
            self._preset_action(self.pending, int(key) - 1)
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
            self._preset_action("recall", int(key) - 1)
        elif key == "P":
            self.pending, self.message = "save", "save preset: press 1-9"
        elif key == "C":
            self.pending, self.message = "clear", "clear preset: press 1-9"
        elif key == "b":
            if self._powered():
                self.state.one_push_white_balance()
                self._record("one push white balance")
        elif key == "f":
            self.state.autofocus = not self.state.autofocus
            self._record(f"autofocus {'on' if self.state.autofocus else 'off'}")
        elif key == "o":
            self.state.power = not self.state.power
            if not self.state.power:
                self.state.stop_all()
            self._record(f"power {'on' if self.state.power else 'standby'}")
        elif key == "n":
            if self.current_view != "network" or self.help_visible:
                self.scroll = 0
            self.current_view, self.help_visible = "network", False
        elif key == "c":
            if self.current_view != "camera" or self.help_visible:
                self.scroll = 0
            self.current_view, self.help_visible = "camera", False
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
        shown = number + 1  # presets are shown 1-based, the wire value is 0-based
        if action == "save":
            self.state.save_preset(number)
            self._record(f"save preset {shown}")
        elif action == "clear":
            self.state.clear_preset(number)
            self._record(f"clear preset {shown}")
        elif self._powered():
            if self.state.recall_preset(number):
                self._finish_if_instant()
                self._record(f"recall preset {shown}")
            else:
                self.message = f"preset {shown} is empty"

    def _finish_if_instant(self) -> None:
        if self.camera.instant:
            self.state.finish_moves()

    def _record(self, description: str) -> None:
        self.camera.record(SOURCE, description)
        self.message = description

    # ---------------------------------------------------------------- output
    def frame(self, title: str, log_lines: int = 10) -> List[str]:
        """Render view content without the fixed interactive chrome."""
        if self.current_view == "network":
            return render_network(title, color=False, bind_address=self.bind_address).splitlines()
        return render_camera(self.camera, title, color=False, log_lines=log_lines).splitlines()

    def layout(self, title: str, width: int, height: int) -> Tuple[List[str], Optional[ViewBox]]:
        """Fit scrollable content between fixed view, status and command bars."""
        if width < MIN_TERMINAL_COLS or height < MIN_TERMINAL_ROWS:
            footer = self.shortcuts(width, height)
            footer = footer[-height:] if height > 0 else []
            room = max(height - len(footer), 0)
            view_name = self.current_view.upper()
            if self.help_visible:
                view_name = f"HELP | {view_name}"
            notice = [
                f"{view_name} | Terminal too small",
                f"Minimum: {MIN_TERMINAL_COLS} columns, {MIN_TERMINAL_ROWS} rows",
                f"Current: {width} columns, {height} rows",
            ]
            if room == 1:
                notice = [f"Resize: {MIN_TERMINAL_COLS}x{MIN_TERMINAL_ROWS}"]
            lines = notice[:room] + [""] * max(room - len(notice), 0) + footer
            return [line[:max(width, 0)] for line in lines], None

        footer = self.shortcuts(width, height)
        room = height - 3 - len(footer)
        view_name = self.current_view.upper()
        heading = "Network Information" if self.current_view == "network" else "PTZ camera simulator"
        header = f"{view_name} | {heading}"
        if self.help_visible:
            header = f"HELP | {view_name}"
        camera_tab = "[c]:Camera" if self.current_view == "camera" else "c:Camera"
        network_tab = "[n]:Network" if self.current_view == "network" else "n:Network"
        tabs = f"{camera_tab}  {network_tab}  | {title}"
        if self.help_visible:
            content = ["Keyboard commands", ""] + [
                f"{key:<14} {description}" for key, description in COMMANDS
            ] + ["", "Space stops the camera even in help.",
                 "Camera controls also work in Network view."]
        else:
            content = self.frame(title)[1:]
        if content and not content[0]:
            content = content[1:]
        box = None
        picture: List[str] = []
        side_by_side = (not self.help_visible and self.current_view == "camera"
                        and width >= DASHBOARD_WIDTH + 2 + MIN_VIEW_COLS
                        and room >= MIN_VIEW_ROWS)
        content_width = DASHBOARD_WIDTH if side_by_side else width
        content = [part for line in content
                   for part in (textwrap.wrap(line, content_width, subsequent_indent="  ",
                                             replace_whitespace=False) or [""])]
        if not self.help_visible and self.current_view == "camera":
            if side_by_side:
                cols = min(width - DASHBOARD_WIDTH - 2, MAX_VIEW_COLS)
                rows = min(room, _view_rows(cols))
                picture, self.view_styles = framed_picture(self.state, cols, rows)
                box = (2, DASHBOARD_WIDTH + 2, rows, cols)

        self._page_rows = max(1, room)
        self.scroll = min(self.scroll, max(0, len(content) - room))
        body = content[self.scroll:self.scroll + room]
        body += [""] * (room - len(body))
        if side_by_side:
            col = DASHBOARD_WIDTH + 2
            body = [line.ljust(col) + (picture[i] if i < len(picture) else "")
                    for i, line in enumerate(body)]
        status = self.message or f"Speed {self.speed}/{SPEED_LEVELS} | Ready"
        if self.pending:
            status = f"{self.pending} preset: press 1-9 | Esc cancel"
        if len(content) > room and not self.pending:
            position = f"{self.scroll + 1}-{min(self.scroll + room, len(content))}/{len(content)}"
            available = max(0, width - len(position) - 3)
            text = status[:available].rstrip(" |")
            status = f"{text.ljust(available)} | {position}"
        lines = [header, tabs] + body + [status] + footer
        return [line[:width] for line in lines], box

    def shortcuts(self, width: int, height: int) -> List[str]:
        """Group commands by purpose, keeping essential actions on small screens."""
        if width < MIN_TERMINAL_COLS or height < MIN_TERMINAL_ROWS:
            if width >= 22:
                return ["[Space] Stop  [q] Quit"]
            return ["[Space] Stop", "[q] Quit"]
        if self.help_visible:
            return ["[Space] Stop  [PgUp/PgDn] Scroll",
                    "[c/n] View  [?/Esc] Back  [q] Quit"]
        if height < 15:
            return ["[Space] Stop  [PgUp/PgDn] Scroll", "[?] Help  [q] Quit"]
        groups = [
            ("MOVE", [[("[Arrows/WASD]", "Pan/Tilt")],
                      [("[+/-]", "Zoom"), ("[h]", "Home")],
                      [("[Space]", "Stop"), ("[ / ]", "Speed")]]),
            ("PRESET", [[("[1-9]", "Recall")], [("[P then 1-9]", "Save")],
                        [("[C then 1-9]", "Clear")]]),
            ("CAMERA", [[("[f]", "Autofocus")], [("[b]", "White balance")],
                        [("[o]", "Power")]]),
            ("VIEW", [[("[c]", "Camera")], [("[n]", "Network"), ("[?]", "Help")],
                      [("[PgUp/PgDn]", "Scroll"), ("[q]", "Quit")]]),
        ]
        columns = []
        for label, rows in groups:
            key_width = max(len(row[0][0]) for row in rows)
            action_width = max(len(row[0][1]) for row in rows)
            second_width = max((len(row[1][0]) for row in rows if len(row) > 1), default=0)
            cells = [label]
            for row in rows:
                key, action = row[0]
                if len(row) == 1:
                    cells.append(f"{key:<{key_width}} {action}")
                else:
                    second_key, second_action = row[1]
                    cells.append(f"{key:<{key_width}} {action:<{action_width}}  "
                                 f"{second_key:<{second_width}} {second_action}")
            columns.append(cells)
        widths = [max(len(cell) for cell in column) for column in columns]
        return [
            "      ".join(cell.ljust(widths[index]) if index < len(row) - 1 else cell
                          for index, cell in enumerate(row))
            for row in zip(*columns)
        ]


def _view_rows(cols: int) -> int:
    """Rows for a 16:9 picture ``cols`` wide (cells are about twice as high as wide)."""
    return round((cols - 2) * 9 / 16 / CELL_ASPECT) + 2


CURSES_KEYS = {"KEY_UP": "UP", "KEY_DOWN": "DOWN", "KEY_LEFT": "LEFT", "KEY_RIGHT": "RIGHT",
               "KEY_PPAGE": "PAGEUP", "KEY_NPAGE": "PAGEDOWN"}


async def interactive(camera: ViscaCamera, title: str, interval: float = 0.05,
                      bind_address: str = "0.0.0.0") -> None:
    """Run the interactive UI until the user presses q (needs a terminal with curses)."""
    import curses

    controller = TuiController(camera, bind_address=bind_address)
    os.environ.setdefault("ESCDELAY", "100")
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
        colors = _init_colors()
        while not controller.quit:
            while True:
                try:
                    key = screen.getkey()
                except curses.error:  # no input pending
                    break
                if key == "\x1b":
                    key = _escape_sequence(screen)
                elif key == "KEY_RESIZE" and sys.platform == "win32":
                    curses.resize_term(0, 0)  # PDCurses (windows-curses) only adopts the new size on request
                controller.handle_key(CURSES_KEYS.get(key, key))
            controller.tick()
            height, width = screen.getmaxyx()
            lines, view = controller.layout(title, width, height)
            _draw(screen, lines, view, colors, controller.view_styles,
                  footer_rows=len(controller.shortcuts(width, height)) + 1)
            await asyncio.sleep(interval)
    finally:
        screen.keypad(False)
        curses.nocbreak()
        curses.echo()
        curses.endwin()


ARROW_SEQUENCES = {"[A": "UP", "[B": "DOWN", "[C": "RIGHT", "[D": "LEFT",
                   "OA": "UP", "OB": "DOWN", "OC": "RIGHT", "OD": "LEFT",
                   "[5~": "PAGEUP", "[6~": "PAGEDOWN"}


def _escape_sequence(screen) -> str:
    """Arrow keys the terminfo entry does not know arrive as raw ESC [ C / ESC O C."""
    import curses

    sequence = ""
    for _ in range(3):
        try:
            sequence += screen.getkey()
        except curses.error:
            break
        if sequence in ARROW_SEQUENCES:
            break
    return ARROW_SEQUENCES.get(sequence, "ESC")


def _init_colors() -> dict:
    """Colour attributes of the chrome (empty without colour support); picture colours
    are added on demand by ``_style_attr``."""
    import curses

    try:
        if not curses.has_colors():
            return {}
        curses.start_color()
        curses.use_default_colors()
    except curses.error:
        return {}
    colors: dict = {}
    for number, (name, foreground, background) in enumerate([
        ("header", curses.COLOR_WHITE, curses.COLOR_BLUE),
        ("commands", curses.COLOR_WHITE, curses.COLOR_BLUE),
        ("shortcut", curses.COLOR_BLACK, curses.COLOR_CYAN),
        ("status", curses.COLOR_BLACK, curses.COLOR_WHITE),
    ], start=1):
        curses.init_pair(number, foreground, background)
        colors[name] = curses.color_pair(number)
    colors["_pairs"] = {}  # (fg, bg) -> attribute, for the picture
    return colors


def _style_attr(colors: dict, style: Optional[str]) -> int:
    """curses attribute for a picture style "fg[/bg][+bold]" (see scenery.Paint)."""
    if not style or not colors:
        return 0
    key = ("style", style)
    if key not in colors:
        import curses

        names, _, flag = style.partition("+")
        bold = curses.A_BOLD if flag == "bold" or names == "bold" else 0
        attr = bold
        if names != "bold":
            fg, _, bg = names.partition("/")
            pair = (getattr(curses, "COLOR_" + fg.upper()),
                    getattr(curses, "COLOR_" + bg.upper()) if bg else -1)
            pairs = colors["_pairs"]
            if pair not in pairs:
                number = 5 + len(pairs)  # 1-4 are the chrome colours
                try:
                    curses.init_pair(number, *pair)
                    pairs[pair] = curses.color_pair(number)
                except curses.error:  # out of colour pairs
                    pairs[pair] = 0
            attr |= pairs[pair]
        colors[key] = attr
    return colors[key]


def _draw(screen, lines: List[str], view: Optional[ViewBox], colors: dict,
          styles: Optional[Styles] = None, footer_rows: int = 0) -> None:
    import curses

    height, width = screen.getmaxyx()
    screen.erase()
    footer_start = len(lines) - footer_rows
    for row, line in enumerate(lines[:height]):
        if row < 2:
            attr = colors.get("header", curses.A_REVERSE) | curses.A_BOLD
        elif footer_rows and row >= footer_start:
            name = "status" if row == footer_start else "commands"
            attr = colors.get(name, curses.A_REVERSE)
        else:
            attr = curses.A_NORMAL
        try:
            screen.addnstr(row, 0, line.ljust(width), width, attr)
        except curses.error:  # Writing the lower-right cell can report ERR after drawing it.
            pass
        if row == 1:
            for tab in ("[c]:Camera", "[n]:Network"):
                col = line.find(tab)
                if col >= 0:
                    screen.addnstr(row, col, tab, min(len(tab), width - col),
                                   colors.get("shortcut", curses.A_NORMAL) | curses.A_BOLD)
        elif footer_rows and row > footer_start:
            for match in re.finditer(r"\[[^\[\]]+\]", line):
                try:
                    screen.addnstr(row, match.start(), match.group(), len(match.group()),
                                   colors.get("shortcut", curses.A_NORMAL) | curses.A_BOLD)
                except curses.error:
                    pass
    if view and colors:
        top, left, rows, cols = view
        # Colour the inside of the picture, not its border.
        for row in range(top + 1, min(top + rows - 1, height - 1)):
            line = lines[row]
            style_row = (styles or [])[row - top - 1] if row - top - 1 < len(styles or []) else []
            for col in range(left + 1, min(left + cols - 1, width - 1, len(line))):
                index = col - left - 1
                attr = _style_attr(colors, style_row[index] if index < len(style_row) else None)
                if attr:
                    try:
                        screen.addstr(row, col, line[col], attr)
                    except curses.error:
                        pass
    screen.refresh()
