"""Text-mode camera picture: what the simulated camera sees at its current pan/tilt/zoom.

Same virtual scene as the NDI test picture (``ndi.SceneRenderer``): a horizon at 0°
tilt, a 5° checker pattern, a post every 45° of pan labelled with its angle and a
crosshair in the centre. Standard library only.
"""

from __future__ import annotations

from typing import List

from . import state as st

BASE_FOV = 60.0  # horizontal field of view at 1x, degrees (as in ndi.SceneRenderer)
CELL_ASPECT = 2.0  # a terminal cell is about twice as high as wide
POST_SPACING = 45
POST_TOP = 8.0  # posts reach from the ground up to this elevation, degrees
LABEL_ELEVATION = 11.0

# Characters, also used by the TUI to pick colours.
SKY, STAR, GROUND_A, GROUND_B, FINE = " ", "·", ".", ":", "+"
HORIZON, POST, CROSS = "─", "│", "◎"


def _on_line(value: float, spacing: float, cell: float) -> bool:
    """True if a grid line every ``spacing`` degrees falls into the cell starting at value.

    Half-open cells, so a line is drawn in exactly one column/row.
    """
    offset = (value + cell / 2) % spacing
    return offset < cell - 1e-9  # tolerance: a line exactly on a cell edge belongs to one cell


def render_view(s: st.CameraState, cols: int, rows: int) -> List[str]:
    """Render the picture as ``rows`` strings of ``cols`` characters (without border)."""
    if not s.power:
        blank = [" " * cols for _ in range(rows)]
        text = "STANDBY"
        if rows and cols >= len(text):
            mid = rows // 2
            start = (cols - len(text)) // 2
            blank[mid] = blank[mid][:start] + text + blank[mid][start + len(text):]
        return blank

    fov = BASE_FOV / s.zoom_ratio
    dx = fov / cols  # degrees per column
    dy = dx * CELL_ASPECT  # degrees per row
    cx, cy = cols // 2, rows // 2  # the crosshair cell shows exactly pan/tilt
    fine_grid = dx < 0.25  # 1° grid once zoomed in far enough to see it

    grid = []
    for r in range(rows):
        el = s.tilt_degrees - (r - cy) * dy
        row = []
        for c in range(cols):
            az = s.pan_degrees + (c - cx) * dx
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
        grid.append(row)

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

    if rows and cols:
        grid[cy][cx] = CROSS
    return ["".join(row) for row in grid]


def framed_view(s: st.CameraState, cols: int, rows: int) -> List[str]:
    """The picture with a border and a caption; ``cols``/``rows`` include the border."""
    inner_cols, inner_rows = max(1, cols - 2), max(1, rows - 2)
    caption = f" Camera {s.pan_degrees:+.1f}° {s.tilt_degrees:+.1f}° {s.zoom_ratio:.1f}x "
    top = "┌" + caption[:inner_cols].ljust(inner_cols, "─") + "┐"
    body = ["│" + line + "│" for line in render_view(s, inner_cols, inner_rows)]
    return [top] + body + ["└" + "─" * inner_cols + "┘"]
