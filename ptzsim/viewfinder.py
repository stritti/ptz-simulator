# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Text-mode camera picture: what the simulated camera sees at its current pan/tilt/zoom.

Same virtual scene as the NDI test picture (``ndi.SceneRenderer``): a horizon at 0°
tilt, a 5° checker pattern, a post every 45° of pan labelled with its angle, the
landmarks of ``scenery`` (mountains, a house, a UFO, ...) and a crosshair in the
centre. Standard library only.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from . import scenery
from . import state as st

BASE_FOV = 60.0  # horizontal field of view at 1x, degrees (as in ndi.SceneRenderer)
CELL_ASPECT = 2.0  # a terminal cell is about twice as high as wide
POST_SPACING = 45
POST_TOP = 8.0  # posts reach from the ground up to this elevation, degrees
LABEL_ELEVATION = 11.0

# Characters, also used by the TUI to pick colours.
SKY, STAR, GROUND_A, GROUND_B, FINE = " ", "·", ".", ":", "+"
HORIZON, POST, CROSS = "─", "│", "◎"

# Terminal colours ("fg[/bg][+bold]", see scenery.Paint) of the background characters.
STYLES = {
    STAR: "blue", GROUND_A: "green", GROUND_B: "green", POST: "red",
    CROSS: "yellow+bold", FINE: "cyan", HORIZON: "bold",
}

Styles = List[List[Optional[str]]]


def _on_line(value: float, spacing: float, cell: float) -> bool:
    """True if a grid line every ``spacing`` degrees falls into the cell starting at value.

    Half-open cells, so a line is drawn in exactly one column/row.
    """
    offset = (value + cell / 2) % spacing
    return offset < cell - 1e-9  # tolerance: a line exactly on a cell edge belongs to one cell


def render_view(s: st.CameraState, cols: int, rows: int) -> List[str]:
    """Render the picture as ``rows`` strings of ``cols`` characters (without border)."""
    return render_picture(s, cols, rows)[0]


def render_picture(s: st.CameraState, cols: int, rows: int) -> Tuple[List[str], Styles]:
    """The picture's lines plus the terminal colour of every cell (None: default)."""
    if not s.power:
        blank = [" " * cols for _ in range(rows)]
        text = "STANDBY"
        if rows and cols >= len(text):
            mid = rows // 2
            start = (cols - len(text)) // 2
            blank[mid] = blank[mid][:start] + text + blank[mid][start + len(text):]
        return blank, [[None] * cols for _ in range(rows)]

    fov = BASE_FOV / s.zoom_ratio
    dx = fov / cols  # degrees per column
    dy = dx * CELL_ASPECT  # degrees per row
    cx, cy = cols // 2, rows // 2  # the crosshair cell shows exactly pan/tilt
    fine_grid = dx < 0.25  # 1° grid once zoomed in far enough to see it
    landmarks = scenery.visible(s.pan_degrees - (cx + 1) * dx, s.pan_degrees + (cols - cx) * dx,
                                s.tilt_degrees - (rows - cy) * dy, s.tilt_degrees + (cy + 1) * dy)

    grid, styles = [], []
    for r in range(rows):
        el = s.tilt_degrees - (r - cy) * dy
        row, style = [], []
        in_row = [lm for lm in landmarks if lm.el <= el <= lm.top]
        for c in range(cols):
            az = s.pan_degrees + (c - cx) * dx
            hit = scenery.cell_at(in_row, az, el, dx, dy) if in_row else None
            if hit is not None:
                row.append(hit[0])
                style.append(hit[1].term)
                continue
            if _on_line(el, 360, dy):
                ch = HORIZON
            elif el < POST_TOP and _on_line(az, POST_SPACING, dx):
                ch = POST
            elif fine_grid and (_on_line(az, 1, dx) or _on_line(el, 1, dy)):
                ch = FINE
            elif el > 0:
                ch = STAR if _on_line(az, 5, dx) and _on_line(el, 5, dy) else SKY
            else:
                checker = (int(az // 5) + int(el // 5)) % 2
                ch = GROUND_A if checker else GROUND_B
            row.append(ch)
            style.append(STYLES.get(ch))
        grid.append(row)
        styles.append(style)

    # Angle labels above the posts.
    label_row = round(cy - (LABEL_ELEVATION - s.tilt_degrees) / dy)
    if 0 <= label_row < rows:
        first = int((s.pan_degrees - fov) // POST_SPACING) * POST_SPACING
        for angle in range(first, int(s.pan_degrees + fov) + POST_SPACING, POST_SPACING):
            label = f"{angle}°"
            col = round(cx + (angle - s.pan_degrees) / dx) - len(label) // 2
            for i, ch in enumerate(label):
                if 0 <= col + i < cols:
                    grid[label_row][col + i] = ch
                    styles[label_row][col + i] = None

    if rows and cols:
        grid[cy][cx] = CROSS
        styles[cy][cx] = STYLES[CROSS]
    return ["".join(row) for row in grid], styles


def framed_view(s: st.CameraState, cols: int, rows: int) -> List[str]:
    """The picture with a border and a caption; ``cols``/``rows`` include the border."""
    return framed_picture(s, cols, rows)[0]


def framed_picture(s: st.CameraState, cols: int, rows: int) -> Tuple[List[str], Styles]:
    """``framed_view`` plus the colours of the picture inside the border."""
    inner_cols, inner_rows = max(1, cols - 2), max(1, rows - 2)
    caption = f" Camera {s.pan_degrees:+.1f}° {s.tilt_degrees:+.1f}° {s.zoom_ratio:.1f}x "
    top = "┌" + caption[:inner_cols].ljust(inner_cols, "─") + "┐"
    lines, styles = render_picture(s, inner_cols, inner_rows)
    body = ["│" + line + "│" for line in lines]
    return [top] + body + ["└" + "─" * inner_cols + "┘"], styles
