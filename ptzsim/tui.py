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
Span = Tuple[int, int, int, str]  # row, column, length, style ("fg[/bg][+bold][+dim]" or a CHROME name)

PRODUCT = "PTZ-Simulator"
SPEED_LEVELS = 8
DASHBOARD_WIDTH = 80  # widest dashboard line (the command log, see display.LOG_WIDTH)
MIN_TERMINAL_COLS, MIN_TERMINAL_ROWS = DASHBOARD_WIDTH, 8
HEADER_ROWS = 2  # the header line and a blank line below it
MIN_VIEW_COLS, MAX_VIEW_COLS = 30, 200
MIN_VIEW_ROWS = 8
MIN_LOG_LINES = 5
MESSAGE_SECONDS = 4.0  # how long feedback stays in the status line
# Terminals report key presses but no releases, so a jog runs while the key repeats
# and stops this long after the last repeat.
JOG_TIMEOUT = 0.35
SOURCE = "TUI"

PAN_TILT_KEYS = {
    "LEFT": (-1, 0), "RIGHT": (1, 0), "UP": (0, 1), "DOWN": (0, -1),
    "a": (-1, 0), "d": (1, 0), "w": (0, 1), "s": (0, -1),
}
ZOOM_KEYS = {"+": 1, "=": 1, "-": -1}

TABS = [("c", "Camera", "camera"), ("n", "Network", "network"), ("?", "Help", "help")]

# The help page, grouped like the key legend.
HELP = [
    ("MOVE", [("Arrows/WASD", "pan/tilt while held"), ("+/-", "zoom tele/wide while held"),
              ("Space", "stop all movement"), ("[ / ]", "speed down/up"), ("h", "home position")]),
    ("PRESET", [("1-9", "recall preset"), ("P then 1-9", "save preset"),
                ("C then 1-9", "clear preset")]),
    ("CAMERA", [("f", "toggle autofocus"), ("b", "one-push white balance"),
                ("o", "power on/standby")]),
    ("VIEW", [("c / n", "camera / network view"), ("PgUp/PgDn", "scroll content"),
              ("? / Esc", "open/close help; cancel preset"), ("q", "quit simulator")]),
]
COMMANDS = [command for _, commands in HELP for command in commands]

LEGEND = [
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
# For terminals narrower than the full legend.
MEDIUM_LEGEND = [
    "[Arrows/WASD] Pan/Tilt  [+/-] Zoom  [Space] Stop  [ / ] Speed  [h] Home",
    "[1-9] Preset  [P/C 1-9] Save/Clear  [PgUp/PgDn] Scroll  [?] Help  [q] Quit",
]

# Named styles of the chrome.
CHROME = {"accent": "black/cyan+bold", "key": "cyan+bold", "plain": ""}


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
        self.spans: List[Span] = []  # colours of the text from the last layout()

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
            self._warn("camera is in standby (press o)")
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
                self._warn(f"preset {shown} is empty")

    def _finish_if_instant(self) -> None:
        if self.camera.instant:
            self.state.finish_moves()

    def _record(self, description: str) -> None:
        self.camera.record(SOURCE, description)
        self.message = description

    # ---------------------------------------------------------------- output
    @property
    def message(self) -> str:
        """Feedback for the last key; it fades from the status line after a few seconds."""
        return self._message

    @message.setter
    def message(self, text: str) -> None:
        self._message = text
        self._message_at = self.clock()
        self._message_error = False

    def _warn(self, text: str) -> None:
        self.message = text
        self._message_error = True

    def frame(self, title: str, log_lines: int = 10, color: bool = False) -> List[str]:
        """Render view content without the fixed interactive chrome."""
        if self.current_view == "network":
            return render_network(title, color=color, bind_address=self.bind_address).splitlines()
        return render_camera(self.camera, title, color=color, log_lines=log_lines).splitlines()

    def layout(self, title: str, width: int, height: int) -> Tuple[List[str], Optional[ViewBox]]:
        """Fit scrollable content between the fixed header, status line and key legend.

        The colours of the result are in ``spans`` (text) and ``view_styles`` (picture).
        """
        self.spans = []
        if width < MIN_TERMINAL_COLS or height < MIN_TERMINAL_ROWS:
            return self._too_small(width, height), None

        footer = self.shortcuts(width, height)
        room = height - HEADER_ROWS - 1 - len(footer)
        side_by_side = (not self.help_visible and self.current_view == "camera"
                        and width >= DASHBOARD_WIDTH + 2 + MIN_VIEW_COLS
                        and room >= MIN_VIEW_ROWS)
        content_width = DASHBOARD_WIDTH if side_by_side else width
        content: List[Tuple[str, List[Span]]] = []
        for text, spans in self._content(title, room):
            if len(text) <= content_width:
                content.append((text, spans))
            else:  # a wrapped line loses its colours; rare (long IPv6 lists, ONVIF details)
                content += [(part, []) for part in textwrap.wrap(
                    text, content_width, subsequent_indent="  ", replace_whitespace=False)]

        box = None
        picture: List[str] = []
        if side_by_side:
            cols = min(width - DASHBOARD_WIDTH - 3, _view_cols(room), MAX_VIEW_COLS)
            rows = min(room, _view_rows(cols))
            picture, self.view_styles = framed_picture(self.state, cols, rows)
            box = (HEADER_ROWS, DASHBOARD_WIDTH + 2, rows, cols)

        self._page_rows = max(1, room)
        self.scroll = min(self.scroll, max(0, len(content) - room))
        body = content[self.scroll:self.scroll + room]
        body += [("", [])] * (room - len(body))
        lines = self._header(title, width)
        for index, (text, spans) in enumerate(body):
            row = len(lines)
            if side_by_side and index < len(picture):
                text = text.ljust(DASHBOARD_WIDTH + 2) + picture[index]
            self.spans += [(row, col, length, style) for col, length, style in spans]
            lines.append(text)
        lines.append(self._status(width, len(content), room, row=len(lines)))
        legend_start = len(lines)
        lines += footer
        self._legend_spans(footer, legend_start)
        return [line[:width] for line in lines], box

    # The parts of the layout, each adding its colours to self.spans.
    def _header(self, title: str, width: int) -> List[str]:
        """One quiet line: product, view tabs (the active one highlighted), endpoint."""
        text = PRODUCT
        self.spans.append((0, 0, len(PRODUCT), "bold"))
        active = "help" if self.help_visible else self.current_view
        text += "  "
        for key, label, view in TABS:
            tab = f" [{key}] {label} "
            if view == active:
                self.spans.append((0, len(text), len(tab), "accent"))
            else:
                self.spans.append((0, len(text) + 1, len(key) + 2, "key"))
            text += tab
        room = width - len(text) - 2
        if room >= 8:
            shown = title if len(title) <= room else title[:room - 1] + "…"
            self.spans.append((0, width - len(shown), len(shown), "dim"))
            text = text.ljust(width - len(shown)) + shown
        return [text] + [""] * (HEADER_ROWS - 1)

    def _status(self, width: int, content_rows: int, room: int, row: int) -> str:
        """A rule between content and legend: feedback left, camera state right."""
        if self.pending:
            left, left_style = f"{self.pending} preset: press 1-9 | Esc cancel", "bold"
        elif self._message and self.clock() - self._message_at < MESSAGE_SECONDS:
            left, left_style = self._message, "red" if self._message_error else None
        else:
            left, left_style = "Ready", "dim"
        parts: List[Tuple[str, Optional[str]]] = []
        if not self.state.power:
            parts.append(("STANDBY", "red+bold"))
        parts.append((f"Speed {self.speed}/{SPEED_LEVELS}", None))
        parts.append(("AF" if self.state.autofocus else "MF", None))
        if self.camera.errors:
            count = len(self.camera.errors)
            plural = "" if count == 1 else "s"
            parts.append((f"{count}{'+' if count == self.camera.errors.maxlen else ''} error{plural}",
                          "red"))
        if content_rows > room:
            first, last = self.scroll + 1, min(self.scroll + room, content_rows)
            parts.append((f"{first}-{last}/{content_rows}", "dim"))
        right = " · ".join(text for text, _ in parts)
        while len(right) + 6 > width and len(parts) > 1:  # keep the scroll position
            parts.pop(-2)
            right = " · ".join(text for text, _ in parts)
        available = width - len(right) - 6
        if len(left) > available:
            left = left[:max(0, available - 1)].rstrip(" |") + "…"
        line = f"─ {left} ".ljust(width - len(right) - 1, "─") + " " + right
        self.spans.append((row, 0, len(line), "dim"))  # the rule itself
        if left_style != "dim":
            self.spans.append((row, 2, len(left), left_style or "plain"))
        col = width - len(right)
        for index, (text, style) in enumerate(parts):
            self.spans.append((row, col, len(text), style or "plain"))
            col += len(text) + 3
        return line

    def _legend_spans(self, footer: List[str], start: int) -> None:
        for offset, line in enumerate(footer):
            for match in re.finditer(r"\[[^\[\]]+\]", line):
                self.spans.append((start + offset, match.start(), len(match.group()), "key"))
            for match in re.finditer(r"\b(MOVE|PRESET|CAMERA|VIEW)\b", line):
                self.spans.append((start + offset, match.start(), len(match.group()), "dim"))

    def _content(self, title: str, room: int) -> List[Tuple[str, List[Span]]]:
        """The scrollable lines of the current view, with their colours."""
        if self.help_visible:
            return self._help()
        if self.current_view == "camera":
            # The command log takes the rows the rest of the dashboard leaves free.
            fixed = len(self.frame(title, log_lines=0)) - 1  # without the view title
            text = self.frame(title, log_lines=max(MIN_LOG_LINES, room - fixed), color=True)
        else:
            text = self.frame(title, color=True)
        lines = [_parse_ansi(line) for line in text[1:]]  # the view title is in the header
        if lines and not lines[0][0]:
            lines = lines[1:]
        return lines

    def _help(self) -> List[Tuple[str, List[Span]]]:
        lines: List[Tuple[str, List[Span]]] = [("Keyboard commands", [(0, 17, "bold")]), ("", [])]
        for group, commands in HELP:
            lines.append((group, [(0, len(group), "dim")]))
            for key, description in commands:
                lines.append((f"  {key:<14} {description}", [(2, len(key), "key")]))
            lines.append(("", []))
        lines.append(("Space stops the camera even in help; camera keys also work in Network view.",
                      [(0, 5, "key")]))
        return lines

    def _too_small(self, width: int, height: int) -> List[str]:
        footer = self.shortcuts(width, height)
        footer = footer[-height:] if height > 0 else []
        room = max(height - len(footer), 0)
        view_name = "Help" if self.help_visible else self.current_view.capitalize()
        notice = [
            f"{view_name} | Terminal too small",
            f"Minimum: {MIN_TERMINAL_COLS} columns, {MIN_TERMINAL_ROWS} rows",
            f"Current: {width} columns, {height} rows",
        ]
        if room == 1:
            notice = [f"Resize: {MIN_TERMINAL_COLS}x{MIN_TERMINAL_ROWS}"]
        if room:
            self.spans.append((0, 0, len(notice[0]), "bold"))
        lines = notice[:room] + [""] * max(room - len(notice), 0)
        self._legend_spans(footer, len(lines))
        return [line[:max(width, 0)] for line in lines + footer]

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
        legend = _legend()
        if max(map(len, legend)) <= width:
            return legend
        return [line for line in MEDIUM_LEGEND]


def _legend() -> List[str]:
    """The full key legend: four groups side by side, keys and actions aligned."""
    columns = []
    for label, rows in LEGEND:
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


SGR_STYLES = {"31": "red", "32": "green"}


def _parse_ansi(line: str) -> Tuple[str, List[Span]]:
    """Split a line with ANSI colour codes (from ``display``) into text and colour spans."""
    text, spans = "", []
    colour, flags = None, []
    for part in re.split(r"(\x1b\[[0-9;]*m)", line):
        code = re.fullmatch(r"\x1b\[([0-9;]*)m", part)
        if code:
            for number in (code.group(1) or "0").split(";"):
                if number in ("", "0"):
                    colour, flags = None, []
                elif number in SGR_STYLES:
                    colour = SGR_STYLES[number]
                elif number == "1":
                    flags.append("bold")
                elif number == "2":
                    flags.append("dim")
            continue
        if part and (colour or flags):
            style = "+".join([colour or ""] + flags).lstrip("+")
            spans.append((len(text), len(part), style))
        text += part
    stripped = text.rstrip()
    spans = [(col, min(length, len(stripped) - col), style)
             for col, length, style in spans if col < len(stripped)]
    return stripped, spans


def _view_rows(cols: int) -> int:
    """Rows for a 16:9 picture ``cols`` wide (cells are about twice as high as wide)."""
    return round((cols - 2) * 9 / 16 / CELL_ASPECT) + 2


def _view_cols(rows: int) -> int:
    """The widest 16:9 picture that fits into ``rows`` rows."""
    return int((rows - 2) * CELL_ASPECT * 16 / 9) + 2


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
                keys = [key]
                if key == "\x1b":
                    keys = _escape_sequence(screen)
                elif key == "KEY_RESIZE" and sys.platform == "win32":
                    curses.resize_term(0, 0)  # PDCurses (windows-curses) only adopts the new size on request
                for key in keys:
                    controller.handle_key(CURSES_KEYS.get(key, key))
            controller.tick()
            height, width = screen.getmaxyx()
            lines, view = controller.layout(title, width, height)
            _draw(screen, lines, view, colors, controller.view_styles, controller.spans)
            await asyncio.sleep(interval)
    finally:
        screen.keypad(False)
        curses.nocbreak()
        curses.echo()
        curses.endwin()


ARROW_SEQUENCES = {"[A": "UP", "[B": "DOWN", "[C": "RIGHT", "[D": "LEFT",
                   "OA": "UP", "OB": "DOWN", "OC": "RIGHT", "OD": "LEFT",
                   "[5~": "PAGEUP", "[6~": "PAGEDOWN"}


def _escape_sequence(screen) -> List[str]:
    """Arrow keys the terminfo entry does not know arrive as raw ESC [ C / ESC O C.

    Any other key right after ESC is a key of its own (Esc, then c), so it is kept.
    """
    import curses

    sequence = ""
    for _ in range(3):
        try:
            sequence += screen.getkey()
        except curses.error:
            break
        if sequence in ARROW_SEQUENCES or sequence[0] not in "[O":
            break
    if sequence in ARROW_SEQUENCES:
        return [ARROW_SEQUENCES[sequence]]
    if sequence and sequence[0] not in "[O":
        return ["ESC", sequence]
    return ["ESC"]


def _init_colors() -> dict:
    """Colour support (empty without it); colour pairs are added on demand by ``_style_attr``."""
    import curses

    try:
        if not curses.has_colors():
            return {}
        curses.start_color()
        curses.use_default_colors()
    except curses.error:
        return {}
    return {"_pairs": {}}  # (fg, bg) -> attribute


def _style_attr(colors: dict, style: Optional[str]) -> int:
    """curses attribute for a style "fg[/bg][+bold][+dim]" (see scenery.Paint) or a CHROME name.

    Without colour support only bold and dim remain, and a background becomes reverse video.
    """
    if not style:
        return 0
    style = CHROME.get(style, style)
    key = ("style", style)
    if key in colors:
        return colors[key]
    import curses

    names, *flags = style.split("+")
    if names in ("bold", "dim"):
        names, flags = "", flags + [names]
    attr = 0
    if "bold" in flags:
        attr |= curses.A_BOLD
    if "dim" in flags:
        attr |= getattr(curses, "A_DIM", 0)
    fg, _, bg = names.partition("/")
    if not colors:
        return attr | (curses.A_REVERSE if bg else 0)
    if fg:
        pair = (getattr(curses, "COLOR_" + fg.upper()),
                getattr(curses, "COLOR_" + bg.upper()) if bg else -1)
        pairs = colors["_pairs"]
        if pair not in pairs:
            number = 1 + len(pairs)
            try:
                curses.init_pair(number, *pair)
                pairs[pair] = curses.color_pair(number)
            except curses.error:  # out of colour pairs
                pairs[pair] = 0
        attr |= pairs[pair]
    colors[key] = attr
    return attr


def _draw(screen, lines: List[str], view: Optional[ViewBox], colors: dict,
          styles: Optional[Styles] = None, spans: Optional[List[Span]] = None) -> None:
    import curses

    height, width = screen.getmaxyx()
    screen.erase()
    for row, line in enumerate(lines[:height]):
        try:
            screen.addnstr(row, 0, line.ljust(width), width, curses.A_NORMAL)
        except curses.error:  # Writing the lower-right cell can report ERR after drawing it.
            pass
    for row, col, length, style in spans or []:
        if row >= min(height, len(lines)) or col >= width or length <= 0:
            continue
        attr = _style_attr(colors, style)
        if not attr:
            continue
        text = lines[row].ljust(width)[col:col + length]
        try:
            screen.addnstr(row, col, text, min(len(text), width - col), attr)
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
