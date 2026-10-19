"""Command line entry point: ``ptzsim serve`` and ``ptzsim send``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import socket
import sys
from typing import List, Optional

from .display import dashboard, log_printer
from .transports import (SONY_HEADER, SONY_VISCA_COMMAND, SONY_VISCA_INQUIRY,
                         Simulator, serve_pty, serve_tcp, serve_udp)
from .onvif import OnvifCamera, serve_discovery, serve_onvif
from .visca import ViscaCamera, hexdump, parse_hex

DEFAULT_PORTS = {"sony": 52381, "tcp": 5678, "udp": 1259, "onvif": 8080}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ptzsim", description="PTZ camera simulator (ONVIF, VISCA and NDI)")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run a simulated camera")
    serve.add_argument("--host", default="0.0.0.0", help="address to listen on (default 0.0.0.0)")
    serve.add_argument("--sony", type=int, metavar="PORT", nargs="?", const=DEFAULT_PORTS["sony"],
                       help="Sony VISCA over IP on UDP (default port 52381)")
    serve.add_argument("--tcp", type=int, metavar="PORT", nargs="?", const=DEFAULT_PORTS["tcp"],
                       help="raw VISCA over TCP, e.g. PTZOptics (default port 5678)")
    serve.add_argument("--udp", type=int, metavar="PORT", nargs="?", const=DEFAULT_PORTS["udp"],
                       help="raw VISCA over UDP (default port 1259)")
    serve.add_argument("--pty", nargs="?", const="", metavar="LINK",
                       help="emulate a serial port via a pseudo terminal; optional symlink path")
    serve.add_argument("--onvif", type=int, metavar="PORT", nargs="?", const=DEFAULT_PORTS["onvif"],
                       help="ONVIF (SOAP over HTTP) with WS-Discovery (default port 8080)")
    serve.add_argument("--onvif-user", metavar="USER", help="require WS-Security UsernameToken with this user")
    serve.add_argument("--onvif-password", metavar="PASSWORD", default="", help="password for --onvif-user")
    serve.add_argument("--ndi", action="store_true",
                       help="publish an NDI source with PTZ control (needs: pip install ndi-python numpy)")
    serve.add_argument("--ndi-fps", type=int, default=25, metavar="FPS", help="NDI frame rate (default 25)")
    serve.add_argument("--name", default="PTZ-Simulator", help="camera name (ONVIF scope/profile, NDI source name)")
    serve.add_argument("--no-discovery", action="store_true", help="do not answer WS-Discovery probes")
    serve.add_argument("--advertise-host", metavar="IP",
                       help="address announced in WS-Discovery (default: detected per request)")
    serve.add_argument("--onvif-auth", choices=("both", "digest", "wsse"), default="both",
                       help="ONVIF authentication: HTTP digest and/or WS-UsernameToken (default both)")
    serve.add_argument("--onvif-no-absolute", action="store_true",
                       help="simulate a camera without AbsoluteMove (presets only via SetPreset/GotoPreset)")
    serve.add_argument("--rtsp-uri", metavar="URI", help="stream URI returned by ONVIF GetStreamUri")
    serve.add_argument("--address", type=int, default=1, choices=range(1, 8),
                       help="VISCA camera address (default 1)")
    serve.add_argument("--instant", action="store_true",
                       help="jump to target positions instead of moving at motor speed")
    serve.add_argument("--no-tui", action="store_true", help="print one line per command instead of a dashboard")
    serve.add_argument("--view-only", action="store_true",
                       help="show the dashboard without keyboard control")
    serve.add_argument("-v", "--verbose", action="store_true", help="log every packet sent and received")

    send = sub.add_parser("send", help="send VISCA hex packets to a camera and print the replies")
    send.add_argument("packets", nargs="+", help='VISCA packets as hex, e.g. "81 01 06 04 FF"')
    send.add_argument("--host", default="127.0.0.1")
    send.add_argument("--port", type=int)
    send.add_argument("--proto", choices=("sony", "tcp", "udp"), default="sony")
    send.add_argument("--timeout", type=float, default=2.0, help="seconds to wait for replies")
    return parser


async def _serve(args: argparse.Namespace) -> None:
    camera = ViscaCamera(address=args.address, instant=args.instant)
    sim = Simulator(camera)
    endpoints: List[str] = []
    discovery = None

    if all(v is None for v in (args.sony, args.tcp, args.udp, args.pty, args.onvif)) and not args.ndi:
        args.sony = DEFAULT_PORTS["sony"]
    if args.sony is not None:
        await serve_udp(sim, args.host, args.sony, sony=True)
        endpoints.append(f"Sony VISCA/IP udp://{args.host}:{args.sony}")
    if args.tcp is not None:
        await serve_tcp(sim, args.host, args.tcp)
        endpoints.append(f"VISCA tcp://{args.host}:{args.tcp}")
    if args.udp is not None:
        await serve_udp(sim, args.host, args.udp, sony=False)
        endpoints.append(f"VISCA udp://{args.host}:{args.udp}")
    if args.pty is not None:
        endpoints.append(f"VISCA serial {serve_pty(sim, args.pty or None)}")
    if args.onvif is not None:
        onvif = OnvifCamera(camera, name=args.name, username=args.onvif_user,
                            password=args.onvif_password, rtsp_uri=args.rtsp_uri,
                            absolute=not args.onvif_no_absolute, auth=args.onvif_auth)
        await serve_onvif(onvif, args.host, args.onvif)
        endpoints.append(f"ONVIF http://{args.host}:{args.onvif}/onvif/device_service")
        if not args.no_discovery:
            discovery = await serve_discovery(onvif, args.onvif, advertise_host=args.advertise_host)
            endpoints.append("WS-Discovery udp/3702")
    if args.ndi:
        from .ndi import start_ndi

        source = start_ndi(camera, args.name, args.ndi_fps)
        endpoints.append(f"NDI {source.source_name}")

    title = " | ".join(endpoints)
    logging.getLogger("ptzsim").info("listening: %s", title)
    if args.no_tui:
        view = log_printer(camera)
    elif args.view_only or not _interactive_terminal():
        view = dashboard(camera, title)
    else:
        from .tui import interactive

        view = interactive(camera, title)
    tasks = [asyncio.ensure_future(sim.run()), asyncio.ensure_future(view)]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            task.result()  # re-raise errors from the simulator or the view
    finally:
        if discovery is not None:
            discovery.get_protocol().bye()  # WS-Discovery Bye when leaving the network


def _interactive_terminal() -> bool:
    """The keyboard UI needs curses (not on Windows) and a terminal on stdin and stdout."""
    try:
        import curses  # noqa: F401
    except ImportError:
        return False
    return sys.stdin.isatty() and sys.stdout.isatty()


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
    args = build_parser().parse_args(argv)
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
