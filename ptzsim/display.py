"""Terminal dashboard showing the simulated camera."""

from __future__ import annotations

import asyncio
import sys
from typing import List

from . import state as st
from .visca import ViscaCamera

CLEAR = "\x1b[H\x1b[2J"
HIDE_CURSOR, SHOW_CURSOR = "\x1b[?25l", "\x1b[?25h"
GREEN, RED, DIM, BOLD, RESET = "\x1b[32m", "\x1b[31m", "\x1b[2m", "\x1b[1m", "\x1b[0m"


def bar(value: float, low: float, high: float, width: int = 30, center: bool = False) -> str:
    pos = round((value - low) / (high - low) * (width - 1))
    cells = ["─"] * width
    if center:
        zero = round((0 - low) / (high - low) * (width - 1))
        cells[zero] = "┼"
    cells[max(0, min(width - 1, pos))] = "●"
    return "[" + "".join(cells) + "]"


def render(camera: ViscaCamera, title: str, color: bool = True, log_lines: int = 10) -> str:
    s = camera.state
    g, r, d, b, x = (GREEN, RED, DIM, BOLD, RESET) if color else ("",) * 5
    pan, tilt, zoom, focus = s.position()

    def motion(velocity: float, target) -> str:
        if target is not None:
            return f"{g}→ {round(target[0])}{x}"
        if velocity:
            return f"{g}{'▶' if velocity > 0 else '◀'} {abs(velocity):.0f}/s{x}"
        return f"{d}idle{x}"

    lines: List[str] = [
        f"{b}PTZ camera simulator{x}  {d}{title}{x}",
        f"Power: {g + 'ON' if s.power else r + 'STANDBY'}{x}   "
        f"Address: {camera.address}   Commands: {camera.command_count}",
        "",
        f"Pan   {pan:6d}  {s.pan_degrees:+7.1f}°  "
        f"{bar(s.pan, st.PAN_MIN, st.PAN_MAX, center=True)}  {motion(s.pan_velocity, s.pan_target)}",
        f"Tilt  {tilt:6d}  {s.tilt_degrees:+7.1f}°  "
        f"{bar(s.tilt, st.TILT_MIN, st.TILT_MAX, center=True)}  {motion(s.tilt_velocity, s.tilt_target)}",
        f"Zoom  {zoom:#06x}  {s.zoom_ratio:7.1f}x  "
        f"{bar(s.zoom, st.ZOOM_MIN, st.ZOOM_MAX)}  {motion(s.zoom_velocity, s.zoom_target)}",
        f"Focus {focus:#06x}  {'AF' if s.autofocus else 'MF':>8}  "
        f"{bar(s.focus, st.FOCUS_MIN, st.FOCUS_MAX)}  {motion(s.focus_velocity, s.focus_target)}",
        "",
    ]
    if s.presets:
        lines.append(f"{b}Presets{x}")
        for number, p in sorted(s.presets.items()):
            marker = "*" if number == s.last_preset else " "
            lines.append(f" {marker}{number:3d}: pan {p.pan:6d}  tilt {p.tilt:6d}  "
                         f"zoom {p.zoom:#06x}  focus {p.focus:#06x}"
                         + (f"  {p.name}" if p.name else ""))
    else:
        lines.append(f"{d}No presets stored{x}")
    lines += ["", f"{b}Last commands{x}"]
    entries = list(camera.log)[-log_lines:]
    if not entries:
        lines.append(f"{d}(waiting for commands){x}")
    for entry in entries:
        c = "" if entry.ok else r
        lines.append(f" {d}{entry.source:<44}{x} {c}{entry.description}{x}")
    lines += ["", f"{d}Ctrl+C to quit{x}"]
    return "\n".join(lines)


async def dashboard(camera: ViscaCamera, title: str, interval: float = 0.1) -> None:
    out = sys.stdout
    out.write(HIDE_CURSOR)
    try:
        while True:
            out.write(CLEAR + render(camera, title) + "\n")
            out.flush()
            await asyncio.sleep(interval)
    finally:
        out.write(SHOW_CURSOR)
        out.flush()


async def log_printer(camera: ViscaCamera, interval: float = 0.1) -> None:
    """Plain line output for non-interactive use (``--no-tui``)."""
    seen = 0
    while True:
        total = camera.command_count
        new = list(camera.log)[-(total - seen):] if total > seen else []
        seen = total
        for entry in new:
            pan, tilt, zoom, focus = camera.state.position()
            print(f"{entry.source:<44} {entry.description:<36} "
                  f"pan={pan} tilt={tilt} zoom={zoom:#06x}", flush=True)
        await asyncio.sleep(interval)
