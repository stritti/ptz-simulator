# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Terminal dashboard showing the simulated camera."""

from __future__ import annotations

import asyncio
import ipaddress
import sys
import select
import threading
import termios
import tty
import os
import fcntl
from typing import Dict, List, Optional

from . import state as st
from .visca import ViscaCamera
from .network import get_all_interfaces_detailed, get_hostname_and_fqdn, interface_sort_key

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


def render_camera(camera: ViscaCamera, title: str, color: bool = True, log_lines: int = 10) -> str:
    """Render the main camera control view."""
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
    ]

    lines += [
        f"Pan   {pan:6d}  {s.pan_degrees:+7.1f}°  "
        f"{bar(s.pan, st.PAN_MIN, st.PAN_MAX, center=True)}  {motion(s.pan_velocity, s.pan_target)}",
        f"Tilt  {tilt:6d}  {s.tilt_degrees:+7.1f}°  "
        f"{bar(s.tilt, st.TILT_MIN, st.TILT_MAX, center=True)}  {motion(s.tilt_velocity, s.tilt_target)}",
        f"Zoom  {zoom:#06x}  {s.zoom_ratio:7.1f}x  "
        f"{bar(s.zoom, st.ZOOM_MIN, st.ZOOM_MAX)}  {motion(s.zoom_velocity, s.zoom_target)}",
        f"Focus {focus:#06x}  {'AF' if s.autofocus else 'MF':>8}  "
        f"{bar(s.focus, st.FOCUS_MIN, st.FOCUS_MAX)}  {motion(s.focus_velocity, s.focus_target)}",
        f"White balance  {s.white_balance:<12}  R {s.red_gain:#04x}  B {s.blue_gain:#04x}",
        "",
    ]
    if s.presets:
        lines.append(f"{b}Presets{x}")
        for number, p in sorted(s.presets.items()):
            marker = "*" if number == s.last_preset else " "
            lines.append(f" {marker}{number + 1:3d}: pan {p.pan:6d}  tilt {p.tilt:6d}  "
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

    return "\n".join(lines)


def _ipv4_with_prefix(address: str, netmask: str) -> str:
    try:
        return ipaddress.IPv4Interface(f"{address}/{netmask}").with_prefixlen
    except ValueError:
        return address


def render_network(title: str, color: bool = True) -> str:
    """Render the network information view: hostname plus a table of all interfaces."""
    g, r, b, d, x = (GREEN, RED, BOLD, DIM, RESET) if color else ("",) * 5
    hostname, fqdn = get_hostname_and_fqdn()
    interfaces = sorted(get_all_interfaces_detailed().values(), key=interface_sort_key)
    name_width = max([len("Interface")] + [len(iface.name) for iface in interfaces])

    def row(name: str, state: str, ipv4: str, ipv6: str) -> str:
        return f"  {name:<{name_width}}  {state:<5}  {ipv4:<18}  {ipv6}".rstrip()

    lines: List[str] = [
        f"{b}Network Information{x}  {d}{title}{x}",
        "",
        f"{b}Hostname:{x} {hostname}",
        f"{b}FQDN:{x}     {fqdn}",
        "",
        f"{b}Interfaces ({len(interfaces)}){x}",
        f"{b}{row('Interface', 'State', 'IPv4', 'IPv6')}{x}",
    ]
    if not interfaces:
        lines.append(f"  {d}(no network interfaces found){x}")
    for iface in interfaces:
        ipv4 = [_ipv4_with_prefix(addr, netmask) for addr, netmask in iface.ipv4_addresses]
        ipv6 = list(iface.ipv6_addresses)
        if not (ipv4 or ipv6):
            ipv4 = ["–"]
        state = {True: f"{g}up{x}   ", False: f"{r}down{x} ", None: "?    "}[iface.up]
        for i in range(max(len(ipv4), len(ipv6))):
            lines.append(row(iface.name if i == 0 else "", state if i == 0 else "",
                             ipv4[i] if i < len(ipv4) else "", ipv6[i] if i < len(ipv6) else ""))
    return "\n".join(lines)



def render_shortcuts(color: bool = True, current_view: str = "camera") -> str:
    """Render the bottom shortcuts bar with active view indicator."""
    if color:
        b, d, x = BOLD, DIM, RESET
    else:
        b, d, x = "", "", ""

    shortcuts = [
        ("n", "Network", "network"),
        ("c", "Camera", "camera"),
        ("q", "Quit", None),
    ]

    # Build the shortcuts line with active indicator
    shortcut_items = []
    for key, label, view in shortcuts:
        if view and view == current_view:
            # Highlight active view
            shortcut_items.append(f"{b}[{key}]{x}:{label}")
        else:
            shortcut_items.append(f"{b}{key}{x}:{label}")

    # Center and pad the shortcuts to fill the width
    shortcut_str = "  " + "   ".join(shortcut_items) + "  "

    return shortcut_str


def render(camera: ViscaCamera, title: str, color: bool = True, log_lines: int = 10,
          bind_address: str = "0.0.0.0", ports: Optional[Dict[str, int]] = None,
          view: str = "camera") -> str:
    """Render the appropriate view based on the current view mode."""
    b, d, x = (BOLD, DIM, RESET) if color else ("",) * 3

    # Render the main content
    if view == "network":
        content = render_network(title, color)
    else:
        content = render_camera(camera, title, color, log_lines)

    lines = content.split("\n")

    # Add footer with shortcuts
    shortcuts = render_shortcuts(color, view)
    lines.append("")
    lines.append("─" * 120)
    lines.append(shortcuts)

    return "\n".join(lines)


class DashboardState:
    """Manage dashboard state including current view."""
    def __init__(self):
        import threading
        self._lock = threading.Lock()
        self._current_view = "camera"  # "camera" or "network"
        self.should_quit = False

    @property
    def current_view(self):
        with self._lock:
            return self._current_view

    @current_view.setter
    def current_view(self, value):
        with self._lock:
            self._current_view = value

    def switch_view(self, view: str) -> None:
        """Switch to a specific view."""
        if view in ("camera", "network"):
            with self._lock:
                self._current_view = view

    def toggle_view(self) -> None:
        """Switch between views."""
        with self._lock:
            self._current_view = "network" if self._current_view == "camera" else "camera"


async def read_keyboard_input(state: DashboardState, loop) -> None:
    """Read keyboard input in a separate thread."""
    import threading

    def input_reader():
        """Run in a thread to read individual characters."""
        fd = sys.stdin.fileno()
        old_settings = None
        old_fl = None
        is_tty = False

        try:
            # Check if stdin is a TTY
            is_tty = sys.stdin.isatty()

            if is_tty:
                # Save old terminal settings
                old_settings = termios.tcgetattr(fd)
                # Set to raw mode to read individual characters without waiting for Enter
                tty.setraw(fd)

                # Also make it non-blocking
                old_fl = fcntl.fcntl(fd, fcntl.F_GETFL)
                fcntl.fcntl(fd, fcntl.F_SETFL, old_fl | os.O_NONBLOCK)
        except Exception:
            is_tty = False

        try:
            input_buffer = ""

            while not state.should_quit:
                try:
                    # Use select() + os.read() for both TTY and non-TTY modes
                    # This works reliably across all terminal types (VS Code, real TTY, piped input)
                    ready, _, _ = select.select([fd], [], [], 0.1)

                    if ready:
                        try:
                            # Use os.read() on the raw FD - reliable with select()
                            chunk_bytes = os.read(fd, 1024)
                            chunk = chunk_bytes.decode('utf-8', errors='ignore')
                        except Exception:
                            chunk = ""

                        if not chunk:  # EOF
                            state.should_quit = True
                            break

                        input_buffer += chunk

                        # Process each character
                        while input_buffer:
                            ch = input_buffer[0]
                            input_buffer = input_buffer[1:]

                            # Skip whitespace
                            if ch in ('\n', '\r', ' ', '\t'):
                                continue

                            ch = ch.lower()

                            if ch == 'n':
                                state.switch_view('network')
                            elif ch == 'c':
                                state.switch_view('camera')
                            elif ch == 'q':
                                state.should_quit = True
                            elif ch == '\x03':  # Ctrl+C
                                state.should_quit = True
                except Exception:
                    pass

                # Small sleep to avoid busy-waiting
                import time
                time.sleep(0.01)
        finally:
            # Restore old terminal settings
            if is_tty:
                try:
                    if old_fl is not None:
                        fcntl.fcntl(fd, fcntl.F_SETFL, old_fl)
                    if old_settings is not None:
                        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                except Exception:
                    pass

    # Start the input reader thread as a daemon
    reader_thread = threading.Thread(target=input_reader, daemon=True)
    reader_thread.start()

    # Keep the async task alive while the reader thread runs
    try:
        while not state.should_quit:
            await asyncio.sleep(0.1)
    finally:
        reader_thread.join(timeout=0.1)


async def dashboard(camera: ViscaCamera, title: str, interval: float = 0.1,
                  bind_address: str = "0.0.0.0", ports: Optional[Dict[str, int]] = None) -> None:
    out = sys.stdout
    out.write(HIDE_CURSOR)
    state = DashboardState()
    loop = asyncio.get_event_loop()

    # Start the keyboard input reader task
    keyboard_task = asyncio.create_task(read_keyboard_input(state, loop))

    try:
        while not state.should_quit:
            output = render(camera, title, bind_address=bind_address, ports=ports, view=state.current_view)
            out.write(CLEAR + output + "\n")
            out.flush()
            await asyncio.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        keyboard_task.cancel()
        try:
            await keyboard_task
        except asyncio.CancelledError:
            pass
        out.write(SHOW_CURSOR)
        out.flush()


async def log_printer(camera: ViscaCamera, interval: float = 0.1,
                     bind_address: str = "0.0.0.0", ports: Optional[Dict[str, int]] = None) -> None:
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
