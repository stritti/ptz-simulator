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
"""

from __future__ import annotations

import asyncio
import socket
from contextlib import asynccontextmanager
from typing import AsyncIterator

from .protocol import ServeContext
from .transports import Simulator
from .visca import ViscaCamera


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
