# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Test tooling: fault injection, traffic capture and replay.

``ptzsim serve`` options for exercising a PTZ client against real-world network
problems (all off by default), on the VISCA transports (Sony VISCA/IP, TCP, UDP,
pty) and on ONVIF HTTP answers:

- ``--latency MS``, ``--loss PCT``, ``--duplicate PCT``, ``--reorder PCT`` delay,
  drop, repeat or shuffle replies
- ``--disconnect-after N`` closes every client connection after N replies
- ``--capture FILE`` writes every sent/received message to FILE as JSONL
- ``--script FILE`` replays a scripted session (or a ``--capture`` file) into the
  simulator with its original timestamps

Capture format, one JSON object per line::

    {"t": 1.25, "dir": "rx", "transport": "Sony VISCA/IP", "peer": "127.0.0.1:5000",
     "data": "810104070002ff"}
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from .visca import hexdump, parse_hex

log = logging.getLogger("ptzsim")

Send = Callable[[bytes], None]


@dataclass
class FaultConfig:
    """How strongly the simulator mangles the replies (0 = perfect network)."""

    latency_ms: float = 0.0
    loss_pct: float = 0.0
    duplicate_pct: float = 0.0
    reorder_pct: float = 0.0
    disconnect_after: int = 0

    def __post_init__(self) -> None:
        for name in ("loss_pct", "duplicate_pct", "reorder_pct"):
            value = getattr(self, name)
            if not 0.0 <= value <= 100.0:
                raise ValueError(f"--{name.replace('_', '-')} must be within 0..100, got {value:g}")
        if self.latency_ms < 0:
            raise ValueError(f"--latency must be >= 0, got {self.latency_ms:g}")
        if self.disconnect_after < 0:
            raise ValueError(f"--disconnect-after must be >= 0, got {self.disconnect_after}")

    def active(self) -> bool:
        return bool(self.latency_ms or self.loss_pct or self.duplicate_pct
                    or self.reorder_pct or self.disconnect_after)


def config_from_args(args: argparse.Namespace) -> FaultConfig:
    return FaultConfig(latency_ms=args.latency, loss_pct=args.loss, duplicate_pct=args.duplicate,
                       reorder_pct=args.reorder, disconnect_after=args.disconnect_after)


class _Link:
    """Per-connection state of the fault injector."""

    def __init__(self) -> None:
        self.sent = 0
        self.dead = False
        self.last_dropped = False
        self.on_disconnect: Optional[Callable[[], None]] = None


class FaultInjector:
    """Wraps the per-connection ``send`` so replies can be delayed, dropped,
    duplicated, reordered or cut off (simulated client disconnect)."""

    def __init__(self, config: FaultConfig, rng: Optional[random.Random] = None):
        self.config = config
        self.rng = rng or random.Random()
        self.dropped = 0
        self.duplicated = 0
        self.reordered = 0
        self.disconnected = 0
        self._links: dict = {}
        self._pending: set = set()  # scheduled but not yet sent replies

    def _roll(self, pct: float) -> bool:
        return pct > 0 and self.rng.uniform(0, 100) < pct

    def _link(self, transport: str, peer: Optional[str], on_disconnect=None) -> _Link:
        key = (transport, peer)
        link = self._links.get(key)
        if link is None:
            link = _Link()
            link.on_disconnect = on_disconnect
            self._links[key] = link
        elif on_disconnect is not None:
            link.on_disconnect = on_disconnect
        return link

    def last_dropped(self, transport: str, peer: Optional[str]) -> bool:
        """True when the injector dropped the most recent reply of this connection
        (the HTTP layer keeps the connection open then, so the client times out)."""
        link = self._links.get((transport, peer))
        return link is not None and link.last_dropped

    async def wait_pending(self) -> None:
        """Wait until every scheduled (delayed) reply has left."""
        while self._pending:
            await asyncio.sleep(0.005)

    def wrap(self, transport: str, peer: Optional[str], send: Send,
             on_disconnect: Optional[Callable[[], None]] = None) -> Send:
        """Return the send callable for one connection with the faults applied."""
        if not self.config.active():
            return send
        link = self._link(transport, peer, on_disconnect)

        def wrapped(data: bytes) -> None:
            if link.dead:
                return
            cfg = self.config
            if cfg.disconnect_after and link.sent >= cfg.disconnect_after:
                link.dead = True
                self.disconnected += 1
                log.info("%s: disconnecting client %s after %d replies (simulated)",
                         transport, peer, link.sent)
                if link.on_disconnect is not None:
                    try:
                        link.on_disconnect()
                    except Exception as err:
                        log.debug("disconnect hook failed: %s", err)
                return
            link.sent += 1
            if self._roll(cfg.loss_pct):
                link.last_dropped = True
                self.dropped += 1
                log.debug("%s: dropped reply to %s: %s", transport, peer, hexdump(data))
                return
            link.last_dropped = False
            delay = cfg.latency_ms / 1000.0
            if self._roll(cfg.reorder_pct):
                # arrive clearly after later replies that leave now
                delay += self.rng.uniform(delay, delay * 3 + 0.05) if delay else self.rng.uniform(0.05, 0.2)
                self.reordered += 1
            count = 2 if self._roll(cfg.duplicate_pct) else 1
            if count == 2:
                self.duplicated += 1
            loop = asyncio.get_running_loop()
            for _ in range(count):
                def deliver(_send: Send = send, _data: bytes = data) -> None:
                    _safe_send(_send, _data)
                    self._pending.discard(handle)
                handle = loop.call_later(delay, deliver)
                self._pending.add(handle)

        return wrapped


def _safe_send(send: Send, data: bytes) -> None:
    try:
        send(data)
    except (OSError, RuntimeError) as err:  # client went away
        log.debug("send failed: %s", err)


class TrafficCapture:
    """JSONL log of the traffic: one object per line with ``t`` (seconds since
    start), ``dir`` (rx/tx), ``transport``, ``peer``, ``data`` (hex) and ``note``."""

    def __init__(self, path: str):
        self.path = path
        self.started = time.monotonic()
        self._file = open(path, "a", encoding="utf-8")

    def log(self, direction: str, transport: str, peer: Optional[str], data: bytes,
            note: Optional[str] = None) -> None:
        entry = {"t": round(time.monotonic() - self.started, 6), "dir": direction,
                 "transport": transport, "peer": peer, "data": data.hex()}
        if note is not None:
            entry["note"] = note
        self._file.write(json.dumps(entry) + "\n")
        self._file.flush()

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """The test-tooling options of ``ptzsim serve``."""
    group = parser.add_argument_group("fault injection and traffic recording (testing PTZ clients)")
    group.add_argument("--latency", type=float, default=0.0, metavar="MS",
                       help="delay every reply by MS milliseconds (default 0)")
    group.add_argument("--loss", type=float, default=0.0, metavar="PCT",
                       help="drop PCT %% of all replies, 0-100 (default 0)")
    group.add_argument("--duplicate", type=float, default=0.0, metavar="PCT",
                       help="send PCT %% of all replies twice, 0-100 (default 0)")
    group.add_argument("--reorder", type=float, default=0.0, metavar="PCT",
                       help="delay PCT %% of replies so later ones overtake them, 0-100 (default 0)")
    group.add_argument("--disconnect-after", type=int, default=0, metavar="N",
                       help="close every client connection after N replies (0 = never)")
    group.add_argument("--capture", metavar="FILE",
                       help="write all received/sent traffic to FILE as JSONL")
    group.add_argument("--script", metavar="FILE",
                       help="replay a session into the simulator: '<seconds> <hex packet>' per line, "
                            "or a --capture JSONL file (its rx entries with their timestamps)")


def from_args(args: argparse.Namespace) -> Tuple[Optional[FaultInjector], Optional[TrafficCapture]]:
    """Build the injector/capture for parsed serve args (None when switched off)."""
    config = config_from_args(args)
    injector = FaultInjector(config) if config.active() else None
    capture = TrafficCapture(args.capture) if getattr(args, "capture", None) else None
    return injector, capture


def parse_script(path: str) -> List[Tuple[float, bytes]]:
    """Read a replay script into (seconds since start, packet) entries.

    Text format: one ``<seconds> <hex packet>`` per line (``#`` starts a comment).
    A ``--capture`` JSONL file works too: its ``rx`` entries are replayed with
    their recorded timestamps.
    """
    entries: List[Tuple[float, bytes]] = []
    with open(path, "r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("{"):
                try:
                    record = json.loads(line)
                except ValueError as err:
                    raise ValueError(f"{path}:{lineno}: bad JSONL line: {err}")
                if record.get("dir") == "rx" and record.get("data"):
                    entries.append((float(record["t"]), bytes.fromhex(record["data"])))
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                raise ValueError(f"{path}:{lineno}: expected '<seconds> <hex packet>', got {line!r}")
            try:
                at = float(parts[0])
            except ValueError:
                raise ValueError(f"{path}:{lineno}: bad timestamp {parts[0]!r}")
            try:
                packet = parse_hex(parts[1])
            except ValueError as err:
                raise ValueError(f"{path}:{lineno}: bad packet: {err}")
            entries.append((at, packet))
    return entries


async def replay(sim, path: str, capture: Optional[TrafficCapture] = None) -> None:
    """Feed a scripted session into the simulator with its original timing.

    The packets enter through ``sim.process`` like a controller's would; the
    replies go to the capture log (if any) and the command log.
    """
    entries = parse_script(path)
    log.info("replaying %d scripted packets from %s", len(entries), path)

    def send(data: bytes) -> None:
        if capture is not None:
            capture.log("tx", "script", None, data)

    start = time.monotonic()
    for at, packet in entries:
        wait = at - (time.monotonic() - start)
        if wait > 0:
            await asyncio.sleep(wait)
        if capture is not None:
            capture.log("rx", "script", None, packet)
        sim.process(packet, send)
