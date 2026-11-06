# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Plugins for the protocols that ship with ptzsim: VISCA, ONVIF and NDI.

The protocol code itself lives in ``transports.py``, ``onvif.py`` and ``ndi.py``;
this module only connects it to the plugin interface in ``protocol.py``. The
registration order is the order of the options in ``--help`` and of the
endpoints in the dashboard title.
"""

from __future__ import annotations

from typing import List

from .protocol import Endpoint, PortPlugin, ProtocolPlugin, ServeContext, register
from .transports import serve_pty, serve_tcp, serve_udp


@register
class SonyViscaIp(PortPlugin):
    name = "sony"
    title = "Sony VISCA over IP"
    default = True  # started when no protocol option is given
    default_port = 52381
    help = "Sony VISCA over IP on UDP (default port {port})"

    async def start(self, ctx: ServeContext) -> List[Endpoint]:
        port = self.port(ctx.args)
        self.servers.append(await serve_udp(ctx.simulator, ctx.host, port, sony=True))
        return [Endpoint("Sony VISCA/IP", f"udp://{ctx.host}:{port}", port)]


@register
class ViscaTcp(PortPlugin):
    name = "tcp"
    title = "raw VISCA over TCP"
    default_port = 5678
    help = "raw VISCA over TCP, e.g. PTZOptics (default port {port})"

    async def start(self, ctx: ServeContext) -> List[Endpoint]:
        port = self.port(ctx.args)
        self.servers.append(await serve_tcp(ctx.simulator, ctx.host, port))
        return [Endpoint("VISCA", f"tcp://{ctx.host}:{port}", port)]


@register
class ViscaUdp(PortPlugin):
    name = "udp"
    title = "raw VISCA over UDP"
    default_port = 1259
    help = "raw VISCA over UDP (default port {port})"

    async def start(self, ctx: ServeContext) -> List[Endpoint]:
        port = self.port(ctx.args)
        self.servers.append(await serve_udp(ctx.simulator, ctx.host, port, sony=False))
        return [Endpoint("VISCA", f"udp://{ctx.host}:{port}", port)]


@register
class ViscaSerial(ProtocolPlugin):
    name = "pty"
    title = "serial VISCA"

    @classmethod
    def add_arguments(cls, group) -> None:
        group.add_argument("--pty", nargs="?", const="", metavar="LINK",
                           help="emulate a serial port via a pseudo terminal; optional symlink path")

    @classmethod
    def enabled(cls, args) -> bool:
        return args.pty is not None

    async def start(self, ctx: ServeContext) -> List[Endpoint]:
        return [Endpoint("VISCA", f"serial {serve_pty(ctx.simulator, ctx.args.pty or None)}")]


@register
class Onvif(PortPlugin):
    name = "onvif"
    title = "ONVIF"
    default_port = 8080
    help = "ONVIF (SOAP over HTTP) with WS-Discovery (default port {port})"

    def __init__(self) -> None:
        super().__init__()
        self.discovery = None

    @classmethod
    def add_options(cls, group) -> None:
        group.add_argument("--onvif-user", metavar="USER",
                           help="require authentication (see --onvif-auth) with this user")
        group.add_argument("--onvif-password", metavar="PASSWORD", default="", help="password for --onvif-user")
        group.add_argument("--onvif-auth", choices=("both", "digest", "wsse"), default="both",
                           help="ONVIF authentication: HTTP digest and/or WS-UsernameToken (default both)")
        group.add_argument("--onvif-no-absolute", action="store_true",
                           help="simulate a camera without AbsoluteMove (presets only via SetPreset/GotoPreset)")
        group.add_argument("--rtsp-uri", metavar="URI", help="stream URI returned by ONVIF GetStreamUri")
        group.add_argument("--no-discovery", action="store_true", help="do not answer WS-Discovery probes")
        group.add_argument("--advertise-host", metavar="IP",
                           help="address announced in WS-Discovery (default: detected per request)")

    async def start(self, ctx: ServeContext) -> List[Endpoint]:
        from .onvif import OnvifCamera, serve_discovery, serve_onvif

        args, port = ctx.args, self.port(ctx.args)
        onvif = OnvifCamera(ctx.camera, name=ctx.name, username=args.onvif_user,
                            password=args.onvif_password, rtsp_uri=args.rtsp_uri,
                            absolute=not args.onvif_no_absolute, auth=args.onvif_auth)
        self.servers.append(await serve_onvif(onvif, ctx.host, port))
        endpoints = [Endpoint("ONVIF", f"http://{ctx.host}:{port}/onvif/device_service", port)]
        if not args.no_discovery:
            self.discovery = await serve_discovery(onvif, port, advertise_host=args.advertise_host)
            self.servers.append(self.discovery)
            endpoints.append(Endpoint("WS-Discovery", "udp/3702", 3702))
        return endpoints

    def stop(self) -> None:
        if self.discovery is not None:
            self.discovery.get_protocol().bye()  # WS-Discovery Bye when leaving the network
        super().stop()


@register
class Ndi(ProtocolPlugin):
    name = "ndi"
    title = "NDI"

    @classmethod
    def add_arguments(cls, group) -> None:
        group.add_argument("--ndi", action="store_true",
                           help="publish an NDI source with PTZ control (needs: pip install ndi-python numpy)")
        group.add_argument("--ndi-fps", type=int, default=25, metavar="FPS", help="NDI frame rate (default 25)")

    @classmethod
    def enabled(cls, args) -> bool:
        return args.ndi

    async def start(self, ctx: ServeContext) -> List[Endpoint]:
        from .ndi import start_ndi  # optional dependencies, imported only when used

        source = start_ndi(ctx.camera, ctx.name, ctx.args.ndi_fps)
        return [Endpoint("NDI", source.source_name or "")]
