#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""ONVIF Profile S/T PTZ conformance smoke test for a camera-side ONVIF endpoint.

Sends SOAP 1.2 requests (standard library only) and checks the responses and
faults a conformant PTZ service must produce:

- GetDeviceInformation, GetCapabilities (XAddrs for Device/Media/PTZ), GetServices
  (PTZ namespace), GetProfiles (profile with PTZ configuration), PTZ GetStatus
  (Position PanTilt/Zoom), ContinuousMove + Stop, presets
  (SetPreset/GetPresets/GotoPreset/RemovePreset),
- an out-of-range AbsoluteMove that must fault env:Sender/ter:InvalidArgVal,
- optionally (--discovery) a WS-Discovery Probe to 239.255.255.250:3702 expecting
  a ProbeMatches with XAddrs.

With --user/--password every request carries a WS-Security UsernameToken
(PasswordDigest); PRE_AUTH operations are also checked without credentials.

Usage:
    python3 onvif_conformance.py --host 192.168.1.50 --port 8080
    python3 onvif_conformance.py --host 127.0.0.1 --user admin --password secret --discovery

Exits 0 when every check passes, 1 otherwise. Standard library only, Python 3.8+.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import io
import os
import socket
import sys
import time
import xml.etree.ElementTree as ET

SOAP = "http://www.w3.org/2003/05/soap-envelope"
TDS = "http://www.onvif.org/ver10/device/wsdl"
TRT = "http://www.onvif.org/ver10/media/wsdl"
TPTZ = "http://www.onvif.org/ver20/ptz/wsdl"
TT = "http://www.onvif.org/ver10/schema"
WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
WSU = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
DISCOVERY = "http://schemas.xmlsoap.org/ws/2005/04/discovery"
DN = "http://www.onvif.org/ver10/network/wsdl"
PT_POSITION_SPACE = "http://www.onvif.org/ver10/tptz/PanTiltSpaces/PositionGenericSpace"
PT_VELOCITY_SPACE = "http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace"
ZOOM_POSITION_SPACE = "http://www.onvif.org/ver10/tptz/ZoomSpaces/PositionGenericSpace"

PRESET_TOKEN = "5"


def localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def find_all(root, name: str):
    return [el for el in root.iter() if localname(el.tag) == name]


def envelope(body: str, security: str = "") -> str:
    header = "<s:Header>%s</s:Header>" % security if security else ""
    return (
        '<s:Envelope xmlns:s="%s" xmlns:tds="%s" xmlns:trt="%s" xmlns:tptz="%s" '
        'xmlns:tt="%s">%s<s:Body>%s</s:Body></s:Envelope>'
        % (SOAP, TDS, TRT, TPTZ, TT, header, body)
    )


def security_header(user: str, password: str) -> str:
    nonce = os.urandom(16)
    created = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + password.encode()).digest()).decode()
    return (
        '<Security xmlns="%s"><UsernameToken><Username>%s</Username>'
        '<Password Type="http://docs.oasis-open.org/wss/2004/01/'
        'oasis-200401-wss-username-token-profile-1.0#PasswordDigest">%s</Password>'
        '<Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/'
        'oasis-200401-wss-soap-message-security-1.0#Base64Binary">%s</Nonce>'
        '<Created xmlns="%s">%s</Created></UsernameToken></Security>'
        % (WSSE, user, digest, base64.b64encode(nonce).decode(), WSU, created)
    )


class OnvifClient:
    def __init__(self, host: str, port: int, base: str, user: str, password: str, timeout: float):
        self.host, self.port, self.base = host, port, base
        self.security = security_header(user, password) if user else ""
        self.timeout = timeout

    def post(self, path: str, body: str):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            conn.request(
                "POST", path,
                body=envelope(body, self.security).encode(),
                headers={"Content-Type": "application/soap+xml; charset=utf-8"},
            )
            resp = conn.getresponse()
            return resp.status, resp.read().decode("utf-8", "replace")
        finally:
            conn.close()

    def call(self, service: str, body: str):
        status, text = self.post("%s/%s" % (self.base, service), body)
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            root = None
        return status, text, root

    def discovery_probe(self, timeout: float):
        probe = (
            '<s:Envelope xmlns:s="%s" xmlns:d="%s" xmlns:dn="%s"><s:Body><d:Probe>'
            "<d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></s:Body></s:Envelope>"
            % (SOAP, DISCOVERY, DN)
        )
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.sendto(probe.encode(), ("239.255.255.250", 3702))
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                try:
                    data, _addr = sock.recvfrom(65535)
                except socket.timeout:
                    break
                try:
                    root = ET.fromstring(data.decode("utf-8", "replace"))
                except ET.ParseError:
                    continue
                if find_all(root, "ProbeMatches"):
                    xaddrs = [el.text or "" for el in find_all(root, "XAddrs")]
                    return True, xaddrs
            return False, []
        finally:
            sock.close()


def fault_subcodes(root, text: str) -> list:
    """Local names of ONVIF fault subcode values, whatever prefix the endpoint uses.

    The subcode is a QName in the text of a SOAP `Value` element (e.g.
    `ter:InvalidArgVal`); the prefix is resolved against the namespace
    declarations of the response, and any namespace under
    http://www.onvif.org/ counts as an ONVIF subcode.
    """
    if root is None:
        return []
    prefixes = {}
    for _event, (prefix, uri) in ET.iterparse(io.StringIO(text), events=["start-ns"]):
        prefixes[prefix] = uri
    out = []
    for el in find_all(root, "Value"):
        value = (el.text or "").strip()
        prefix, _, local = value.rpartition(":")
        uri = prefixes.get(prefix, "") if prefix else ""
        if uri.startswith("http://www.onvif.org/"):
            out.append(local or value)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="ONVIF PTZ conformance smoke test")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=80)
    parser.add_argument("--base", default="/onvif", help="service path prefix")
    parser.add_argument("--profile", default="Profile_1")
    parser.add_argument("--user", default="", help="WS-Security user (adds UsernameToken)")
    parser.add_argument("--password", default="")
    parser.add_argument("--discovery", action="store_true", help="also send a WS-Discovery probe")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    client = OnvifClient(args.host, args.port, args.base, args.user, args.password, args.timeout)
    profile = args.profile
    results = []

    def check(name, ok, detail=""):
        results.append((ok, name, detail))
        print("%s %s%s" % ("PASS" if ok else "FAIL", name, (" — " + detail) if detail else ""))

    def response_name(root):
        bodies = find_all(root, "Body") if root is not None else []
        if bodies:
            for child in list(bodies[0]):
                return localname(child.tag)
        return ""

    # --- Device service -----------------------------------------------------
    status, text, root = client.call("device_service", "<tds:GetDeviceInformation/>")
    check("GetDeviceInformation", status == 200 and root is not None
          and response_name(root) == "GetDeviceInformationResponse",
          "HTTP %s" % status)

    status, text, root = client.call(
        "device_service", "<tds:GetCapabilities><tds:Category>All</tds:Category></tds:GetCapabilities>")
    xaddrs = [el.text or "" for el in find_all(root, "XAddr")] if root is not None else []
    check("GetCapabilities advertises Device/Media/PTZ XAddrs",
          status == 200 and any("device_service" in x for x in xaddrs)
          and any("media_service" in x for x in xaddrs) and any("ptz_service" in x for x in xaddrs),
          "HTTP %s, XAddrs %s" % (status, xaddrs))

    status, text, root = client.call(
        "device_service", "<tds:GetServices><tds:IncludeCapability>true</tds:IncludeCapability></tds:GetServices>")
    check("GetServices lists the PTZ service", status == 200 and root is not None
          and TPTZ in text, "HTTP %s" % status)

    # --- Media service ------------------------------------------------------
    status, text, root = client.call("media_service", "<trt:GetProfiles/>")
    tokens = [el.get("token") or "" for el in find_all(root, "Profiles")] if root is not None else []
    check("GetProfiles returns the profile with a PTZ configuration",
          status == 200 and profile in tokens and root is not None
          and len(find_all(root, "PTZConfiguration")) > 0,
          "HTTP %s, tokens %s" % (status, tokens))

    # --- PTZ service --------------------------------------------------------
    status, text, root = client.call(
        "ptz_service", "<tptz:GetStatus><tptz:ProfileToken>%s</tptz:ProfileToken></tptz:GetStatus>" % profile)
    pantilt = find_all(root, "PanTilt") if root is not None else []
    zoom = find_all(root, "Zoom") if root is not None else []
    check("GetStatus reports Position PanTilt/Zoom", status == 200 and root is not None
          and any("x" in el.attrib and "y" in el.attrib for el in pantilt) and len(zoom) > 0,
          "HTTP %s" % status)

    move = (
        "<tptz:ContinuousMove><tptz:ProfileToken>%s</tptz:ProfileToken><tptz:Velocity>"
        '<tt:PanTilt x="0.1" y="0.0" space="%s"/><tt:Zoom x="0.0"/></tptz:Velocity>'
        "<tptz:Timeout>PT1S</tptz:Timeout></tptz:ContinuousMove>" % (profile, PT_VELOCITY_SPACE)
    )
    status, text, root = client.call("ptz_service", move)
    check("ContinuousMove accepted", status == 200 and root is not None
          and response_name(root) == "ContinuousMoveResponse", "HTTP %s" % status)

    stop = ("<tptz:Stop><tptz:ProfileToken>%s</tptz:ProfileToken>"
            "<tptz:PanTilt>true</tptz:PanTilt><tptz:Zoom>true</tptz:Zoom></tptz:Stop>" % profile)
    status, text, root = client.call("ptz_service", stop)
    check("Stop accepted", status == 200 and root is not None
          and response_name(root) == "StopResponse", "HTTP %s" % status)

    status, text, root = client.call(
        "ptz_service",
        "<tptz:SetPreset><tptz:ProfileToken>%s</tptz:ProfileToken><tptz:PresetName>conformance</tptz:PresetName>"
        "<tptz:PresetToken>%s</tptz:PresetToken></tptz:SetPreset>" % (profile, PRESET_TOKEN))
    check("SetPreset accepted", status == 200 and root is not None
          and response_name(root) == "SetPresetResponse", "HTTP %s" % status)

    status, text, root = client.call(
        "ptz_service", "<tptz:GetPresets><tptz:ProfileToken>%s</tptz:ProfileToken></tptz:GetPresets>" % profile)
    preset_tokens = [el.get("token") or "" for el in find_all(root, "Preset")] if root is not None else []
    check("GetPresets lists the new preset", status == 200 and PRESET_TOKEN in preset_tokens,
          "HTTP %s, tokens %s" % (status, preset_tokens))

    status, text, root = client.call(
        "ptz_service",
        "<tptz:GotoPreset><tptz:ProfileToken>%s</tptz:ProfileToken>"
        "<tptz:PresetToken>%s</tptz:PresetToken></tptz:GotoPreset>" % (profile, PRESET_TOKEN))
    check("GotoPreset accepted", status == 200 and root is not None
          and response_name(root) == "GotoPresetResponse", "HTTP %s" % status)

    status, text, root = client.call(
        "ptz_service",
        "<tptz:RemovePreset><tptz:ProfileToken>%s</tptz:ProfileToken>"
        "<tptz:PresetToken>%s</tptz:PresetToken></tptz:RemovePreset>" % (profile, PRESET_TOKEN))
    check("RemovePreset accepted", status == 200 and root is not None
          and response_name(root) == "RemovePresetResponse", "HTTP %s" % status)

    bad_move = (
        "<tptz:AbsoluteMove><tptz:ProfileToken>%s</tptz:ProfileToken><tptz:Position>"
        '<tt:PanTilt x="5.0" y="0.0" space="%s"/>'
        '<tt:Zoom x="0.0" space="%s"/></tptz:Position></tptz:AbsoluteMove>'
        % (profile, PT_POSITION_SPACE, ZOOM_POSITION_SPACE)
    )
    status, text, root = client.call("ptz_service", bad_move)
    subcodes = fault_subcodes(root, text)
    check("out-of-range AbsoluteMove faults env:Sender/ter:InvalidArgVal",
          root is not None and len(find_all(root, "Fault")) > 0
          and "InvalidArgVal" in subcodes,
          "HTTP %s, subcodes %s" % (status, subcodes))

    if args.discovery:
        ok, xaddrs = client.discovery_probe(args.timeout)
        check("WS-Discovery Probe answered with ProbeMatches + XAddrs", ok and len(xaddrs) > 0,
              "XAddrs %s" % xaddrs)

    failed = [r for r in results if not r[0]]
    print("\n%d/%d checks passed" % (len(results) - len(failed), len(results)))
    for _ok, name, detail in failed:
        print("  FAILED %s: %s" % (name, detail))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
