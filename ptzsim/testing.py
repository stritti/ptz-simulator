# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Helpers for testing protocol plugins end to end.

Example (see ``tests/test_protocol.py``)::

    def test_my_protocol():
        async def run():
            port = free_port()
            async with serve("--myproto", str(port)) as ctx:
                reply = await ctx.loop.run_in_executor(None, talk_to, port)
            return ctx, reply

        ctx, reply = asyncio.run(run())
        assert reply == b"OK"
        assert ctx.state.pan_degrees == 10

Client-side checks: drive ptzsim with the client under test, then assert on the
camera model with :func:`assert_stopped` and :func:`assert_no_errors`::

    async with serve("--onvif", str(port), instant=False) as ctx:
        await client.pan_left(); await client.stop()
        assert_stopped(ctx.state)   # no axis may keep moving after Stop
        assert_no_errors(ctx.camera)  # no syntax error, fault or control error
"""

from __future__ import annotations

import asyncio
import socket
from contextlib import asynccontextmanager
from typing import AsyncIterator, Iterable, List

from .protocol import ServeContext
from .transports import Simulator
from .state import CameraState
from .visca import LogEntry, ViscaCamera

#: The motor axes of the camera model.
AXES = ("pan", "tilt", "zoom", "focus")


def free_port(kind: int = socket.SOCK_STREAM) -> int:
    """A port on 127.0.0.1 that is free right now (TCP by default, ``SOCK_DGRAM`` for UDP)."""
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@asynccontextmanager
async def serve(*argv: str, instant: bool = True, tick_interval: float = 0.01) -> AsyncIterator[ServeContext]:
    """Start the plugins that ``ptzsim serve <argv>`` would start, on 127.0.0.1.

    The motor physics run while the ``async with`` block is active; afterwards the
    plugins are stopped. ``instant`` (default True) makes moves finish at once.
    No dashboard is shown.
    """
    from .cli import build_parser

    args = build_parser().parse_args(["serve", "--host", "127.0.0.1", *argv])
    args.instant = args.instant or instant
    camera = ViscaCamera(address=args.address, instant=args.instant)
    ctx = ServeContext(camera, Simulator(camera, tick_interval=tick_interval), args)
    task = asyncio.ensure_future(ctx.simulator.run())
    try:
        await ctx.start_plugins()
        yield ctx
    finally:
        task.cancel()
        ctx.stop_plugins()
        # Transports close their sockets in a loop callback; let it run so the
        # ports are free again when the context is left.
        await asyncio.sleep(0)


def moving_axes(state: CameraState, axes: Iterable[str] = AXES) -> List[str]:
    """The ``axes`` that are still moving: a continuous velocity or a pending target."""
    return [
        axis for axis in axes
        if getattr(state, f"{axis}_velocity") != 0.0 or getattr(state, f"{axis}_target") is not None
    ]


def assert_stopped(state: CameraState, axes: Iterable[str] = AXES) -> None:
    """Fail when one of ``axes`` still moves.

    Use it after the client sent Stop, or after a move that set an axis to speed 0:
    a client that leaves an axis out of an ONVIF ContinuousMove (instead of sending
    velocity 0) keeps that axis running.
    """
    moving = moving_axes(state, axes)
    if moving:
        details = ", ".join(
            "%s (velocity %g, target %s)" % (
                axis, getattr(state, f"{axis}_velocity"), getattr(state, f"{axis}_target"))
            for axis in moving)
        raise AssertionError("still moving: " + details)


def rejected(camera: ViscaCamera) -> List[LogEntry]:
    """Command log entries the camera rejected: VISCA errors, VISCA over IP control
    errors (``0F 01`` / ``0F 02``), ONVIF faults, invalid Pelco-D frames."""
    return [entry for entry in camera.log if not entry.ok]


def assert_no_errors(camera: ViscaCamera) -> None:
    """Fail when the camera rejected a command of the client (see :func:`rejected`)."""
    errors = rejected(camera)
    if errors:
        raise AssertionError("camera rejected: " + "; ".join(
            "%s: %s" % (entry.source, entry.description) for entry in errors))
