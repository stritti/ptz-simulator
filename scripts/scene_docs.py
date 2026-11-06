#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Documentation of the simulated camera scene: tour table, VISCA/ONVIF values and images.

    python3 scripts/scene_docs.py            # rewrite the generated parts of the docs
    python3 scripts/scene_docs.py --check    # fail if they are out of date (used by tests)
    uv run --with numpy python scripts/scene_docs.py --images   # also render the images

The tables in README.md and website/scene.md sit between ``<!-- scene-tour:start -->``
and ``<!-- scene-tour:end -->`` (README) or ``<!-- scene-stops:... -->`` (scene page).
Images go to website/public/images/scene/: the NDI picture (PNG), the TUI viewfinder
(SVG) and a labelled panorama (SVG). The tables need only the standard library.
"""

from __future__ import annotations

import argparse
import base64
import html
import struct
import sys
import zlib
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ptzsim import scenery  # noqa: E402
from ptzsim import state as st  # noqa: E402
from ptzsim.onvif import pan_to_onvif, tilt_to_onvif, zoom_to_onvif  # noqa: E402

README = ROOT / "README.md"
SCENE_PAGE = ROOT / "website" / "scene.md"
IMAGES = ROOT / "website" / "public" / "images" / "scene"
PAN_SPEED, TILT_SPEED = 0x18, 0x14


class Stop(NamedTuple):
    slug: str
    title: str
    text: str
    pan: float  # degrees
    tilt: float  # degrees
    zoom: float  # zoom ratio, 1..20
    detail: bool = False  # a hidden detail: listed under its landmark in the README


TOUR: List[Stop] = [
    Stop("alps", "Alps", "A mountain range with snow caps across 52°–108° of pan.", 80, 6, 1),
    Stop("summit", "Summit cross", "A climber waves next to the cross on the highest peak.",
         78.2, 14.1, 20, True),
    Stop("forest", "Forest", "Fir trees just left of the 0° post, in view at the home position.",
         -18, 4, 1.5),
    Stop("fox", "Fox", "A fox peeks out between the trees.", -14.3, 0.4, 10, True),
    Stop("house", "House", "Smoking chimney, a fence and a cat in the window.", -95, 5, 1.5),
    Stop("sun", "Sun", "The sun wears sunglasses.", -50, 32, 2),
    Stop("birds", "Flock of birds", "A V formation flying east.", 22, 24, 2),
    Stop("straggler", "Straggler", "One bird lags behind and calls for the others.",
         17.8, 24.7, 15, True),
    Stop("plane", "Plane with banner", "Tows a banner that greets every PTZ client.",
         48, 35.5, 2.5),
    Stop("ufo", "UFO", "A flying saucer beams something up from the meadow.", 140, 10, 1.5),
    Stop("cow", "Abducted cow", "The cow in the tractor beam.", 140, 6, 5, True),
    Stop("balloon", "Hot-air balloon", "Red and cream stripes, drifting high.", -140, 24, 2),
    Stop("lake", "Lake", "A lake on the ground in front of the camera.", -60, -9, 2),
    Stop("duck", "Rubber duck", "Floats on the lake.", -63, -7.9, 12, True),
    Stop("nessie", "Lake monster", "Its humps rise out of the water.", -55, -10.2, 8, True),
    Stop("visca-sign", "VISCA billboard", "Shows the VISCA home command.", -165, 2.5, 4),
    Stop("onvif-sign", "ONVIF billboard", "Shows the ONVIF home operation.", 165, 2.5, 4),
    Stop("rocket", "Rocket", "Straight up at 60° of tilt.", 10, 63, 2),
    Stop("treasure", "Buried treasure", "X marks the spot, with a note next to it.",
         30, -27.5, 4),
]


# ----------------------------------------------------------------- coordinates
def camera(stop: Stop) -> st.CameraState:
    return st.CameraState(pan=round(stop.pan * st.UNITS_PER_DEGREE),
                          tilt=round(stop.tilt * st.UNITS_PER_DEGREE), zoom=zoom_units(stop))


def zoom_units(stop: Stop) -> int:
    ratio = min(max(stop.zoom, 1.0), st.MAX_OPTICAL_ZOOM)
    return round(st.ZOOM_MIN + (ratio - 1) / (st.MAX_OPTICAL_ZOOM - 1) * (st.ZOOM_MAX - st.ZOOM_MIN))


def _nibbles(value: int) -> str:
    value &= 0xFFFF
    return " ".join(f"0{(value >> shift) & 0xF:X}" for shift in (12, 8, 4, 0))


def visca(stop: Stop) -> Tuple[str, str]:
    """VISCA AbsolutePosition and Zoom Direct packets that show the stop."""
    s = camera(stop)
    move = (f"81 01 06 02 {PAN_SPEED:02X} {TILT_SPEED:02X} "
            f"{_nibbles(int(s.pan))} {_nibbles(int(s.tilt))} FF")
    return move, f"81 01 04 47 {_nibbles(int(s.zoom))} FF"


def onvif(stop: Stop) -> Tuple[float, float, float]:
    """ONVIF AbsoluteMove values (generic spaces: pan/tilt -1..1, zoom 0..1)."""
    s = camera(stop)
    return pan_to_onvif(s.pan), tilt_to_onvif(s.tilt), zoom_to_onvif(s.zoom)


def _deg(value: float) -> str:
    return f"{value:g}°".replace("-", "−")


# ------------------------------------------------------------------- markdown
def readme_table() -> str:
    rows = ["| Landmark | Pan | Tilt | Zoom |", "|---|---|---|---|"]
    for stop in TOUR:
        name = f"↳ {stop.title}" if stop.detail else stop.title
        rows.append(f"| {name} | {_deg(stop.pan)} | {_deg(stop.tilt)} | {stop.zoom:g}× |")
    return "\n".join(rows)


def scene_table() -> str:
    rows = ["| Landmark | Pan | Tilt | Zoom | ONVIF x / y / zoom |", "|---|---|---|---|---|"]
    for stop in TOUR:
        x, y, z = onvif(stop)
        name = f"↳ [{stop.title}](#{stop.slug})" if stop.detail else f"[{stop.title}](#{stop.slug})"
        rows.append(f"| {name} | {_deg(stop.pan)} | {_deg(stop.tilt)} | {stop.zoom:g}× "
                    f"| {x:.4f} / {y:.4f} / {z:.4f} |")
    return "\n".join(rows)


def scene_stops() -> str:
    parts = []
    for stop in TOUR:
        move, zoom = visca(stop)
        x, y, z = onvif(stop)
        parts.append(f"""### {stop.title} {{#{stop.slug}}}

{stop.text} Pan {_deg(stop.pan)}, tilt {_deg(stop.tilt)}, zoom {stop.zoom:g}×.

<div class="scene-shots">

![{stop.title} in the NDI picture](/images/scene/{stop.slug}-ndi.png)

![{stop.title} in the TUI viewfinder](/images/scene/{stop.slug}-tui.svg)

</div>

```sh
uv run ptzsim send "{move}" "{zoom}"
```

ONVIF `AbsoluteMove`: `PanTilt x="{x:.4f}" y="{y:.4f}"`, `Zoom x="{z:.4f}"`.
""")
    return "\n".join(parts).rstrip("\n")


def _replace(text: str, marker: str, content: str, path: Path) -> str:
    start, end = f"<!-- {marker}:start -->", f"<!-- {marker}:end -->"
    if start not in text or end not in text:
        raise SystemExit(f"{path}: markers {start} / {end} missing")
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    return f"{head}{start}\n{content}\n{end}{tail}"


def generated_docs() -> List[Tuple[Path, str]]:
    readme = _replace(README.read_text(encoding="utf-8"), "scene-tour", readme_table(), README)
    page = SCENE_PAGE.read_text(encoding="utf-8")
    page = _replace(page, "scene-table", scene_table(), SCENE_PAGE)
    page = _replace(page, "scene-stops", scene_stops(), SCENE_PAGE)
    return [(README, readme), (SCENE_PAGE, page)]


# --------------------------------------------------------------------- images
TERM = {"black": "#1b1f24", "red": "#e5534b", "green": "#57ab5a", "yellow": "#d4b23a",
        "blue": "#4f8de0", "magenta": "#c96bd6", "cyan": "#39c5cf", "white": "#c9d1d9"}
BRIGHT = {"black": "#545d68", "red": "#ff7b72", "green": "#7ee787", "yellow": "#f2cc60",
          "blue": "#79c0ff", "magenta": "#e599f7", "cyan": "#76e3ea", "white": "#ffffff"}
TERM_BG, TERM_FG = "#0d1117", "#8b949e"
CELL_W, CELL_H, FONT = 8.4, 17.0, 14


def _style(style: Optional[str]) -> Tuple[str, Optional[str], bool]:
    if not style:
        return TERM_FG, None, False
    colours, _, flag = style.partition("+")
    bold = flag == "bold" or colours == "bold"
    if colours == "bold":
        return "#f0f6fc", None, True
    fg, _, bg = colours.partition("/")
    return (BRIGHT if bold else TERM)[fg], TERM[bg] if bg else None, bold


def tui_svg(s: st.CameraState, cols: int = 74, rows: int = 22) -> str:
    from ptzsim.viewfinder import framed_picture

    lines, styles = framed_picture(s, cols, rows)
    width, height = cols * CELL_W, rows * CELL_H
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.1f} {height:.0f}" '
           f'width="{width:.0f}" height="{height:.0f}" font-family="DejaVu Sans Mono, Menlo, '
           f'Consolas, monospace" font-size="{FONT}">',
           f'<rect width="100%" height="100%" fill="{TERM_BG}"/>']
    for r, line in enumerate(lines):
        y = r * CELL_H
        cells = [None] * cols
        if 0 < r < rows - 1:
            cells = [None] + list(styles[r - 1]) + [None]
        # One <rect> per run of a background colour, one <text> per run of a style.
        runs: List[Tuple[Tuple[str, Optional[str], bool], List[Tuple[int, str]]]] = []
        for c, ch in enumerate(line):
            key = _style(cells[c])
            if runs and runs[-1][0] == key:
                runs[-1][1].append((c, ch))
            else:
                runs.append((key, [(c, ch)]))
        for (fg, bg, bold), run in runs:
            if bg:
                out.append(f'<rect x="{run[0][0] * CELL_W:.1f}" y="{y:.0f}" '
                           f'width="{len(run) * CELL_W + 0.3:.1f}" height="{CELL_H:.0f}" fill="{bg}"/>')
            glyphs = [(c, ch) for c, ch in run if ch != " "]
            if glyphs:
                xs = " ".join(f"{c * CELL_W + CELL_W / 2:.1f}" for c, _ in glyphs)
                text = html.escape("".join(ch for _, ch in glyphs))
                weight = ' font-weight="bold"' if bold else ""
                out.append(f'<text x="{xs}" y="{y + CELL_H * 0.78:.1f}" fill="{fg}" '
                           f'text-anchor="middle"{weight}>{text}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def png(rgb) -> bytes:
    """PNG bytes from an RGB numpy array (standard library zlib, no Pillow)."""
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _rgb(frame):
    import numpy as np

    return np.ascontiguousarray(frame[..., 2::-1])


PANORAMA_PAN = (-200.0, 200.0)
PANORAMA_TILT = (-32.0, 72.0)


def _label_tilt(stop: Stop) -> float:
    """Top of the landmark at a viewpoint, including landmarks stacked on it (beam, UFO)."""
    around = [lm for lm in scenery.LANDMARKS if abs(lm.offset(stop.pan)) <= lm.width / 2]
    top = stop.tilt
    for lm in around:
        if lm.el <= stop.tilt <= lm.top:
            top = max(top, lm.top)
    grown = True
    while grown:
        grown = False
        for lm in around:
            if lm.el <= top + 1 and lm.top > top and lm.el >= stop.tilt - 1:
                top, grown = lm.top, True
    return top


def panorama_svg() -> str:
    """The whole reachable scene with landmark names and pan angles."""
    from ptzsim.ndi import SceneRenderer

    width = 2000
    height = round(width * (PANORAMA_TILT[1] - PANORAMA_TILT[0]) / (PANORAMA_PAN[1] - PANORAMA_PAN[0]))
    renderer = SceneRenderer(width, height)
    renderer.BASE_FOV = PANORAMA_PAN[1] - PANORAMA_PAN[0]
    s = st.CameraState(pan=0, tilt=round(sum(PANORAMA_TILT) / 2 * st.UNITS_PER_DEGREE))
    frame = renderer.render(s)
    cx, cy = width // 2, height // 2  # paint over the crosshair with its neighbours
    frame[cy - 12:cy + 13, cx] = frame[cy - 12:cy + 13, cx - 1]
    frame[cy, cx - 12:cx + 13] = frame[cy - 1, cx - 12:cx + 13]
    data = base64.b64encode(png(_rgb(frame))).decode()
    deg_x = width / (PANORAMA_PAN[1] - PANORAMA_PAN[0])
    tilt_mid = s.tilt / st.UNITS_PER_DEGREE

    def x(pan: float) -> float:
        return (pan - PANORAMA_PAN[0]) * deg_x

    def y(tilt: float) -> float:
        return height / 2 - (tilt - tilt_mid) * deg_x

    axis = 34
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height + axis}" '
           f'font-family="Inter, Helvetica, Arial, sans-serif">',
           f'<image width="{width}" height="{height}" href="data:image/png;base64,{data}"/>',
           f'<rect y="{height}" width="{width}" height="{axis}" fill="#0d1117"/>']
    for pan in range(-180, 181, 45):
        out.append(f'<text x="{x(pan):.0f}" y="{height + 24}" fill="#c9d1d9" font-size="18" '
                   f'text-anchor="middle">{pan}°</text>')
    for limit in (-170, 170):
        out.append(f'<line x1="{x(limit):.0f}" x2="{x(limit):.0f}" y1="0" y2="{height}" '
                   f'stroke="#ffffff" stroke-dasharray="8 8" stroke-opacity="0.7"/>')
    for stop in TOUR:
        if stop.detail:
            continue
        out.append(f'<a href="#{stop.slug}"><text x="{x(stop.pan):.0f}" '
                   f'y="{y(_label_tilt(stop)) - 8:.0f}" fill="#ffffff" stroke="#0d1117" stroke-width="4" '
                   f'paint-order="stroke" font-size="20" font-weight="bold" text-anchor="middle">'
                   f'{html.escape(stop.title)}</text></a>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def write_images() -> None:
    from ptzsim.ndi import SceneRenderer

    IMAGES.mkdir(parents=True, exist_ok=True)
    renderer = SceneRenderer(640, 360)
    for stop in TOUR:
        s = camera(stop)
        (IMAGES / f"{stop.slug}-ndi.png").write_bytes(png(_rgb(renderer.render(s))))
        (IMAGES / f"{stop.slug}-tui.svg").write_text(tui_svg(s), encoding="utf-8")
    (IMAGES / "panorama.svg").write_text(panorama_svg(), encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="only check that the docs are current")
    parser.add_argument("--images", action="store_true", help="also render the images (needs numpy)")
    args = parser.parse_args(argv)
    stale = []
    for path, text in generated_docs():
        if path.read_text(encoding="utf-8") != text:
            stale.append(path)
            if not args.check:
                path.write_text(text, encoding="utf-8")
    if args.check:
        for path in stale:
            print(f"{path.relative_to(ROOT)} is out of date: run python3 scripts/scene_docs.py")
        return 1 if stale else 0
    if args.images:
        write_images()
    return 0


if __name__ == "__main__":
    sys.exit(main())
