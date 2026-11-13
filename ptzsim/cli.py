# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Command line entry point: ``ptzsim serve`` and ``ptzsim send``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import socket
import sys
from typing import List, Optional

from . import faults, protocol
from .display import dashboard, log_printer
from .transports import SONY_HEADER, SONY_VISCA_COMMAND, SONY_VISCA_INQUIRY, Simulator
from .visca import ViscaCamera, hexdump, parse_hex
from .network import get_resolved_addresses, format_network_info_for_startup, format_network_summary

DEFAULT_PORTS = {"sony": 52381, "tcp": 5678, "udp": 1259, "onvif": 8080}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ptzsim", description="PTZ camera simulator (ONVIF, VISCA and NDI)")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run a simulated camera")
    serve.add_argument("--host", default="0.0.0.0", help="address to listen on (default 0.0.0.0)")
    serve.add_argument("--name", default="PTZ-Simulator", help="camera name (ONVIF scope/profile, NDI source name)")
    serve.add_argument("--address", type=int, default=1, choices=range(1, 8),
                       help="VISCA camera address (default 1)")
    serve.add_argument("--instant", action="store_true",
                       help="jump to target positions instead of moving at motor speed")
    serve.add_argument("--no-tui", action="store_true", help="print one line per command instead of a dashboard")
    serve.add_argument("--view-only", action="store_true",
                       help="show the dashboard without keyboard control")
    serve.add_argument("-v", "--verbose", action="store_true", help="log every packet sent and received")
    protocol.add_arguments(serve)  # one option group per protocol plugin
    faults.add_arguments(serve)  # fault injection, capture and replay (test tooling)

    send = sub.add_parser("send", help="send VISCA hex packets to a camera and print the replies")
    send.add_argument("packets", nargs="+", help='VISCA packets as hex, e.g. "81 01 06 04 FF"')
    send.add_argument("--host", default="127.0.0.1")
    send.add_argument("--port", type=int)
    send.add_argument("--proto", choices=("sony", "tcp", "udp"), default="sony")
    send.add_argument("--timeout", type=float, default=2.0, help="seconds to wait for replies")
    return parser


async def _serve(args: argparse.Namespace) -> None:
    injector, capture = faults.from_args(args)
    camera = ViscaCamera(address=args.address, instant=args.instant)
    sim = Simulator(camera, faults=injector, capture=capture)
    ctx = protocol.ServeContext(camera, sim, args, faults=injector, capture=capture)
    try:
        await ctx.start_plugins()
        title = " | ".join(str(e) for e in ctx.endpoints)
        ports = ctx.ports()
        logging.getLogger("ptzsim").info("listening: %s", title)
        loop = asyncio.get_running_loop()

        # Show network information
        if args.host == "0.0.0.0":
            resolved = await loop.run_in_executor(None, get_resolved_addresses, args.host)
            if resolved:
                addr_str = ", ".join(resolved[:3])
                if len(resolved) > 3:
                    addr_str += f", +{len(resolved) - 3} more"
                logging.getLogger("ptzsim").info("Available on: %s", addr_str)

        # Show full network info on startup
        network_info = await loop.run_in_executor(None, format_network_info_for_startup, args.host)
        for line in network_info.split("\n"):
            if line:
                logging.getLogger("ptzsim").info(line)

        if args.no_tui:
            view = log_printer(camera, bind_address=args.host, ports=ports)
        elif args.view_only or not _interactive_terminal():
            notice = None if args.view_only else _curses_hint()
            if notice:
                logging.getLogger("ptzsim").warning(notice)
            view = dashboard(camera, title, bind_address=args.host, ports=ports, notice=notice)
        else:
            from .tui import interactive

            view = interactive(camera, title, bind_address=args.host)
        tasks = [asyncio.ensure_future(sim.run()), asyncio.ensure_future(view)]
        if args.script:
            tasks.append(asyncio.ensure_future(faults.replay(sim, args.script, capture)))
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            task.result()  # re-raise errors from the simulator or the view
    finally:
        ctx.stop_plugins()
        if capture is not None:
            capture.close()


def _has_curses() -> bool:
    try:
        import curses  # noqa: F401
    except ImportError:
        return False
    return True


def _interactive_terminal() -> bool:
    """The keyboard UI needs curses (on Windows: windows-curses) and a terminal on stdin and stdout."""
    return _has_curses() and sys.stdin.isatty() and sys.stdout.isatty()


def _curses_hint() -> Optional[str]:
    """Why the keyboard UI is not shown although it was not switched off, or None."""
    if _has_curses():
        return None  # no terminal (e.g. output piped): nothing the user has to install
    install = "pip install windows-curses" if sys.platform == "win32" else "a Python built with curses"
    return (f"Keyboard control needs the curses module ({install}); "
            "showing the read-only dashboard instead.")


def send_packets(packets: List[bytes], host: str, port: int, proto: str, timeout: float) -> List[bytes]:
    """Send packets to a camera and return all replies received (helper for manual tests)."""
    replies: List[bytes] = []
    if proto == "tcp":
        with socket.create_connection((host, port), timeout=timeout) as sock:
            for packet in packets:
                sock.sendall(packet)
                replies += _collect_stream(sock, timeout)
        return replies

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        for seq, packet in enumerate(packets, start=1):
            if proto == "sony":
                kind = SONY_VISCA_INQUIRY if len(packet) > 1 and packet[1] == 0x09 else SONY_VISCA_COMMAND
                packet = SONY_HEADER.pack(kind, len(packet), seq) + packet
            sock.sendto(packet, (host, port))
            replies += _collect_datagrams(sock, proto == "sony")
    return replies


def _collect_stream(sock: socket.socket, timeout: float) -> List[bytes]:
    buffer = bytearray()
    replies: List[bytes] = []
    while True:
        try:
            data = sock.recv(1024)
        except socket.timeout:
            break
        if not data:
            break
        buffer.extend(data)
        while 0xFF in buffer:
            end = buffer.index(0xFF)
            replies.append(bytes(buffer[: end + 1]))
            del buffer[: end + 1]
        if replies and _is_final(replies[-1]):
            break
    return replies


def _collect_datagrams(sock: socket.socket, sony: bool) -> List[bytes]:
    replies: List[bytes] = []
    while True:
        try:
            data, _ = sock.recvfrom(1024)
        except socket.timeout:
            break
        if sony:
            data = data[SONY_HEADER.size:]
        replies.append(data)
        if _is_final(data):
            break
    return replies


def _is_final(reply: bytes) -> bool:
    """Completion, inquiry answer or error ends a request; an ACK (y0 4z) does not."""
    return len(reply) >= 2 and reply[1] & 0xF0 in (0x50, 0x60) or reply[:1] == b"\x88"


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "serve":
        try:  # validate the test-tooling options before starting anything
            faults.config_from_args(args)
            if args.script:
                faults.parse_script(args.script)
        except (ValueError, OSError) as err:
            parser.error(str(err))
    if args.command == "send":
        port = args.port or DEFAULT_PORTS[args.proto]
        packets = [parse_hex(p) for p in args.packets]
        for reply in send_packets(packets, args.host, port, args.proto, args.timeout):
            print(hexdump(reply))
        return 0

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stderr if args.no_tui else open("ptzsim.log", "a"))
    try:
        asyncio.run(_serve(args))
    except KeyboardInterrupt:
        pass
    except (RuntimeError, OSError) as err:
        print(f"ptzsim: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
