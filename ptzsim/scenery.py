# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Landmarks of the virtual scene: mountains, a house, a UFO and other things to find.

Every landmark stands at a fixed pan/tilt position, so a client that drives the camera
to the same coordinates always sees the same thing, and a wrong conversion shows up
as the wrong picture. Both renderers use this module: the text viewfinder
(``viewfinder.render_view``) and the NDI test picture (``ndi.SceneRenderer``).

A landmark is drawn from text art. One art character covers ``px`` degrees of pan and
``px * ART_ASPECT`` degrees of tilt, like a terminal cell, so at the zoom where one
viewfinder column is ``px`` degrees wide the art appears exactly as written. Small
landmarks (small ``px``) only become recognisable when zoomed in. Standard library only.
"""

from __future__ import annotations

import math
import textwrap
from typing import Dict, List, NamedTuple, Optional, Tuple

EPS = 1e-6
ART_ASPECT = 2.0  # an art character is twice as high as wide, like a terminal cell

BGR = Tuple[int, int, int]


class Paint(NamedTuple):
    """How a character is coloured: in the terminal and in the NDI picture."""

    term: str  # curses colours "fg[/bg][+bold]", e.g. "white/blue+bold"
    bgr: BGR


PAINTS: Dict[str, Paint] = {
    "rock": Paint("white", (120, 112, 105)),
    "snow": Paint("white+bold", (250, 250, 250)),
    "leaf": Paint("green+bold", (40, 135, 30)),
    "wood": Paint("yellow", (30, 65, 115)),
    "sun": Paint("yellow+bold", (0, 215, 255)),
    "ray": Paint("yellow", (90, 235, 255)),
    "shades": Paint("blue+bold", (35, 25, 25)),
    "smile": Paint("red", (40, 40, 190)),
    "roof": Paint("red", (40, 50, 185)),
    "wall": Paint("yellow", (150, 215, 240)),
    "window": Paint("cyan+bold", (235, 215, 150)),
    "door": Paint("magenta", (40, 70, 120)),
    "smoke": Paint("white", (205, 205, 205)),
    "water": Paint("cyan/blue", (195, 115, 35)),
    "hull": Paint("magenta+bold", (200, 90, 200)),
    "dome": Paint("cyan+bold", (240, 240, 140)),
    "light": Paint("yellow+bold", (0, 255, 255)),
    "beam": Paint("green", (150, 250, 160)),
    "bird": Paint("white", (35, 35, 35)),
    "metal": Paint("white+bold", (225, 225, 225)),
    "flame": Paint("red+bold", (0, 120, 255)),
    "mark": Paint("red+bold", (30, 30, 220)),
    "duck": Paint("yellow+bold", (0, 215, 255)),
    "beak": Paint("red+bold", (0, 120, 255)),
    "eye": Paint("blue", (20, 20, 20)),
    "nessie": Paint("green", (60, 125, 40)),
    "cow": Paint("black/white", (240, 240, 240)),
    "cowink": Paint("black/white", (30, 30, 30)),
    "note": Paint("red/yellow", (170, 225, 245)),
    "noteink": Paint("red/yellow+bold", (30, 30, 180)),
    "text": Paint("white+bold", (245, 245, 245)),
    "board": Paint("white/blue", (120, 45, 15)),
    "boardtext": Paint("white/blue+bold", (245, 245, 245)),
    "banner": Paint("white/red", (40, 40, 200)),
    "bannertext": Paint("white/red+bold", (245, 245, 245)),
}

# Default paint per art character; any other character is text in the landmark's ink.
GLYPH_PAINT: Dict[str, str] = {
    "▲": "rock", "^": "snow", "♣": "leaf", "║": "wood", "┃": "wood", "━": "wood",
    "┏": "wood", "┓": "wood", "┗": "wood", "┛": "wood", "┳": "wood", "#": "wood",
    "●": "sun", "*": "ray", "■": "shades", "◡": "smile",
    "▓": "roof", "▒": "wall", "□": "window", "▌": "door", "~": "smoke",
    "≈": "water", "═": "hull", "∩": "dome", "•": "light", "¦": "beam",
    "v": "bird", "█": "metal", "░": "flame", "╳": "mark", "╲": "mark", "╱": "mark",
}

Cell = Tuple[str, Paint]
FILL = "¤"  # art character drawn as a blank in the landmark's fill paint (sign boards)


# How art characters scale when zoomed in (see Landmark.cell); others are text.
SOLID = frozenset(GLYPH_PAINT) - set("━┃║┏┓┗┛┳v╲╱") | {FILL}
H_LINES = frozenset("━_-=")
V_LINES = frozenset("┃║|")
CORNERS = {"┏": "rd", "┓": "ld", "┗": "ru", "┛": "lu", "┳": "lrd"}


def _art(text: str) -> Tuple[str, ...]:
    """Art lines from an indented triple-quoted string (first and last newline dropped)."""
    return tuple(textwrap.dedent(text.strip("\n")).split("\n"))


class Landmark:
    """Text art standing at a fixed position of the panorama."""

    def __init__(self, name: str, az: float, el: float, px: float, art: Tuple[str, ...],
                 ink: str = "text", fill: Optional[str] = None,
                 paints: Optional[Dict[str, str]] = None):
        self.name = name
        self.az = az  # pan of the art's centre, degrees
        self.el = el  # tilt of the art's bottom edge, degrees
        self.px = px  # degrees of pan per art character
        self.art = art
        self.ink = PAINTS[ink]
        self.fill = PAINTS[fill] if fill else None  # paint for FILL characters
        self.paints = {ch: PAINTS[p] for ch, p in (paints or {}).items()}
        self.cols = max(len(line) for line in art)
        self.rows = len(art)
        self.width = self.cols * px
        self.height = self.rows * px * ART_ASPECT

    def __repr__(self) -> str:
        return f"Landmark({self.name!r}, az={self.az}, el={self.el})"

    @property
    def top(self) -> float:
        return self.el + self.height

    def paint(self, ch: str) -> Paint:
        if ch == FILL:
            assert self.fill is not None, f"{self.name}: FILL without a fill paint"
            return self.fill
        if ch in self.paints:
            return self.paints[ch]
        return PAINTS[GLYPH_PAINT[ch]] if ch in GLYPH_PAINT else self.ink

    def offset(self, az: float) -> float:
        """Pan distance from the centre, wrapped to -180..180 degrees."""
        return (az - self.az + 180.0) % 360.0 - 180.0

    def char(self, row: int, col: int) -> Optional[str]:
        """Art character at a grid position, or None where the art is transparent."""
        if not (0 <= row < self.rows and 0 <= col < self.cols):
            return None
        line = self.art[row]
        ch = line[col] if col < len(line) else " "
        return None if ch == " " else ch

    def cell(self, az: float, el: float, dx: float = 0.0, dy: float = 0.0) -> Optional[Cell]:
        """What a viewfinder cell centred on az/el and ``dx`` x ``dy`` degrees big shows.

        Zoomed in beyond the art's own scale an art character covers several cells.
        Solid characters (rock, water, ...) then fill all of them, lines stretch along
        their direction, and text appears once, in the cell at the character's centre.
        Returns None where the landmark is transparent.
        """
        u = (self.offset(az) + self.width / 2) / self.px
        v = (self.top - el) / (self.px * ART_ASPECT)
        col, row = math.floor(u), math.floor(v)
        ch = self.char(row, col)
        if ch is None:
            return None
        if ch in SOLID:
            return (" " if ch == FILL else ch), self.paint(ch)
        # Offset of the cell from the character's centre, in cells (-0.5 .. 0.5 = centre).
        sx = (u - col - 0.5) * self.px / dx if dx else 0.0
        sy = (v - row - 0.5) * self.px * ART_ASPECT / dy if dy else 0.0
        # Half-open with a little slack, so exactly one cell holds the centre even when
        # it falls on a cell border.
        mid_x, mid_y = -0.5 + EPS < sx <= 0.5 + EPS, -0.5 + EPS < sy <= 0.5 + EPS
        shown = None
        if ch in H_LINES:
            shown = ch if mid_y else None
        elif ch in V_LINES:
            shown = ch if mid_x else None
        elif ch in CORNERS:
            arms = CORNERS[ch]
            if mid_x and mid_y:
                shown = ch
            elif mid_y and ("r" if sx > 0 else "l") in arms:
                shown = "━"
            elif mid_x and ("d" if sy > 0 else "u") in arms:
                shown = "┃"
        elif mid_x and mid_y:
            shown = ch
        if shown is not None:
            return shown, self.paint(shown)
        # Around a letter the sign board shows; next to a frame line it is open.
        is_text = ch not in H_LINES and ch not in V_LINES and ch not in CORNERS
        return (" ", self.fill) if self.fill and is_text else None

    def overlaps(self, az_lo: float, az_hi: float, el_lo: float, el_hi: float) -> bool:
        """True if the landmark may be visible in the given direction window."""
        if self.top < el_lo or self.el > el_hi:
            return False
        span, half = az_hi - az_lo, self.width / 2
        if span + self.width >= 360:
            return True
        lo = self.offset(az_lo)  # -180 <= lo < 180; the window may wrap past +180
        return (lo <= half and lo + span >= -half) or lo + span >= 360 - half

    def point(self, row: int, col: int) -> Tuple[float, float]:
        """Pan/tilt of the centre of an art character, degrees."""
        az = self.az - self.width / 2 + (col + 0.5) * self.px
        el = self.top - (row + 0.5) * self.px * ART_ASPECT
        return (az + 180.0) % 360.0 - 180.0, el


def _beam(rows: int, top: int) -> Tuple[str, ...]:
    """A tractor beam that widens towards the ground."""
    widest = top + rows
    return tuple(" " * ((widest - w) // 2) + "¦" * w for w in range(top, widest, 1))


def _sign(*text: str, legs: int = 0) -> Tuple[str, ...]:
    """A framed board with centred text and ``legs`` rows of posts under it."""
    inner = max(len(line) for line in text) + 2
    left, right = inner // 3, inner - inner // 3 - 1
    bottom = "━" * left + ("┳" if legs else "━") + "━" * (right - left - 1)
    bottom += ("┳" if legs else "━") + "━" * (inner - right - 1)
    post = " " * (left + 1) + "┃" + " " * (right - left - 1) + "┃"
    board = ["┏" + "━" * inner + "┓"]
    board += ["┃" + line.center(inner).replace(" ", FILL) + "┃" for line in text]
    return tuple(board + ["┗" + bottom + "┛"] + [post] * legs)


def _plane() -> Tuple[str, ...]:
    """A plane towing a banner."""
    banner = _sign("HELLO, PTZ CLIENT!")
    plane = _art(r"""
          __
          \ \_____
      ==###[o_o___=>
          /_/
    """)
    pad = len(banner[0])
    return (" " * pad + plane[0], banner[0] + plane[1],
            banner[1] + "---" + plane[2][3:], banner[2] + plane[3])


# --------------------------------------------------------------------- the scene
ALPS = Landmark("Alps", az=80, el=0, px=1.0, art=_art("""
                             ^
            ^               ^▲^                    ^
           ^▲^             ^▲▲▲^                  ^▲^
         ^▲▲▲▲^          ▲▲▲▲▲▲▲▲     ^         ▲▲▲▲▲▲
       ▲▲▲▲▲▲▲▲▲      ▲▲▲▲▲▲▲▲▲▲▲▲  ^▲^      ▲▲▲▲▲▲▲▲▲▲
     ▲▲▲▲▲▲▲▲▲▲▲▲▲  ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲  ▲▲▲▲▲▲▲▲▲▲▲▲▲▲
   ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲
"""))

_SUMMIT_AZ, _ = ALPS.point(0, ALPS.art[0].index("^"))
SUMMIT = Landmark("summit cross with a waving climber", az=_SUMMIT_AZ + 0.15, el=ALPS.top,
                  px=0.05, art=_art(r"""
     |   \o/
    -+-   |
     |   / \
"""))

FOREST = Landmark("forest", az=-18, el=0, px=0.6, art=_art("""
       ♣          ♣              ♣
      ♣♣♣   ♣    ♣♣♣     ♣      ♣♣♣
     ♣♣♣♣♣ ♣♣♣  ♣♣♣♣♣   ♣♣♣    ♣♣♣♣♣
    ♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣ ♣♣♣♣♣  ♣♣♣♣♣♣♣
   ♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣♣
       ║    ║     ║      ║       ║
"""))

FOX = Landmark("fox hiding in the forest", az=-14.3, el=0, px=0.08, ink="flame", art=_art(r"""
    /\   /\
   (  o o  )
    \  w  /~~
"""))

HOUSE = Landmark("house with a cat in the window", az=-95, el=0, px=0.5, art=_art("""
              ~ ~
             ~  ~
           ~ ~
       ▓▓▓▓▓▓█▓▓▓
     ▓▓▓▓▓▓▓▓█▓▓▓▓▓
   ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
    ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒       #
    ▒□□□▒▒▒▒▒▒▒=ω=▒▒   # # #
    ▒□□□▒▒▌▌▌▒▒□□□▒▒  ## # #
    ▒▒▒▒▒▒▌▌▌▒▒▒▒▒▒▒ ########
"""), paints={"█": "roof"})

SUN = Landmark("sun with sunglasses", az=-50, el=28, px=0.6, art=_art("""
     *    *    *
        ●●●●●
    *  ●●●●●●●  *
      ●■■■●■■■●
    * ●●●●●●●●● *
      ●●●◡◡◡●●●
    *  ●●●●●●●  *
        ●●●●●
     *    *    *
"""))

BIRDS = Landmark("flock of birds", az=22, el=20, px=0.6, art=_art("""
                v
              v
            v
    v     v
            v
              v
                v
"""))

STRAGGLER = Landmark("straggler bird calling", az=BIRDS.point(3, 0)[0] - 1.1,
                     el=BIRDS.point(3, 0)[1] + 0.4, px=0.08, art=_art("""
    wait for me!
"""))

PLANE = Landmark("plane with a banner", az=48, el=34, px=0.4, ink="bannertext", fill="banner",
                 paints={c: "metal" for c in "_\\/[o=>-"}, art=_plane())

UFO = Landmark("UFO", az=140, el=16, px=0.5, art=_art("""
         ∩∩∩∩∩
      ∩∩∩∩∩∩∩∩∩∩∩
   ═══════════════════
     •  •  •  •  •  •
"""))

BEAM = Landmark("tractor beam", az=140, el=0, px=0.5, art=_beam(rows=16, top=5))

COW = Landmark("abducted cow", az=140, el=5, px=0.25, ink="cowink", fill="cow",
               paints={"^": "cowink"}, art=_art(r"""
           ^__^
           (oo)\_______
           (__)\¤¤¤¤¤¤¤)\/\
               ||----w¤|
               ||     ||
"""))

BALLOON = Landmark("hot air balloon", az=-140, el=20, px=0.5, art=_art(r"""
       ▓▒▓▒▓
     ▓▒▓▒▓▒▓▒▓
    ▓▒▓▒▓▒▓▒▓▒▓
    ▓▒▓▒▓▒▓▒▓▒▓
     ▓▒▓▒▓▒▓▒▓
       ▓▒▓▒▓
        \ /
        ###
"""))

LAKE = Landmark("lake", az=-60, el=-13, px=0.8, art=_art("""
        ≈≈≈≈≈≈≈≈≈≈≈
     ≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈
    ≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈
     ≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈
         ≈≈≈≈≈≈≈≈≈
"""))

DUCK = Landmark("rubber duck", az=-63, el=-8.6, px=0.12,
                paints={"█": "duck", "░": "beak", "■": "eye"}, art=_art("""
       ███
      ██■█░░
       ███
    █  ████
    █████████
     ███████
"""))

NESSIE = Landmark("lake monster", az=-55, el=-10.8, px=0.15,
                  paints={"█": "nessie", "■": "eye"}, art=_art("""
                   ███
                   █■██
     ██     ██     ██
    ████   ████   ███
"""))

VISCA_SIGN = Landmark("VISCA billboard", az=-165, el=0, px=0.4, ink="boardtext", fill="board",
                      art=_sign("VISCA HOME COMMAND", "81 01 06 04 FF", legs=2))

ONVIF_SIGN = Landmark("ONVIF billboard", az=165, el=0, px=0.4, ink="boardtext", fill="board",
                      art=_sign("ONVIF says:", "<tptz:GotoHomePosition/>", legs=2))

ROCKET = Landmark("rocket", az=10, el=60, px=0.5, art=_art(r"""
       ▲
      ███
      █o█
      ███
     /███\
      ░░░
       ░
"""))

TREASURE = Landmark("buried treasure", az=30, el=-28, px=0.3, art=_art("""
    ╲ ╱
     ╳
    ╱ ╲
"""))

TREASURE_NOTE = Landmark("treasure note", az=30, el=-28.3, px=0.06, ink="noteink", fill="note",
                         art=_art("""
    dig¤here!
"""))

# Drawn in this order: a later landmark covers an earlier one.
LANDMARKS: List[Landmark] = [
    ALPS, SUMMIT, FOREST, FOX, HOUSE, SUN, BIRDS, STRAGGLER, PLANE, BEAM, UFO, COW,
    BALLOON, LAKE, DUCK, NESSIE, VISCA_SIGN, ONVIF_SIGN, ROCKET, TREASURE, TREASURE_NOTE,
]


def visible(az_lo: float, az_hi: float, el_lo: float, el_hi: float) -> List[Landmark]:
    """Landmarks that may show in the window, in drawing order."""
    return [lm for lm in LANDMARKS if lm.overlaps(az_lo, az_hi, el_lo, el_hi)]


def cell_at(landmarks: List[Landmark], az: float, el: float,
            dx: float = 0.0, dy: float = 0.0) -> Optional[Cell]:
    """The topmost landmark character in a cell at az/el, or None for the background."""
    for lm in reversed(landmarks):
        hit = lm.cell(az, el, dx, dy)
        if hit is not None:
            return hit
    return None
