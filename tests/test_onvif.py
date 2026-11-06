# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""ONVIF SOAP services and WS-Discovery."""

import asyncio
import base64
import hashlib
import http.client
import json
import os
import socket
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

import pytest

from ptzsim import state as st
from ptzsim.network import InterfaceInfo
from ptzsim.onvif import (OnvifCamera, find, parse_duration, pan_from_onvif, pan_to_onvif,
                          serve_discovery, serve_onvif, text_of, tilt_from_onvif, tilt_to_onvif)
from ptzsim.transports import Simulator
from ptzsim.visca import ViscaCamera, parse_hex

SOAP = ('<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl" xmlns:trt="http://www.onvif.org/ver10/media/wsdl" '
        'xmlns:tds="http://www.onvif.org/ver10/device/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema">'
        '<s:Header>{header}</s:Header><s:Body>{body}</s:Body></s:Envelope>')


def call(onvif, body, header=""):
    status, xml = onvif.handle(SOAP.format(header=header, body=body).encode(), "127.0.0.1:8080")
    return status, ET.fromstring(xml)


def username_token(user, password, nonce=b"0123456789abcdef", created="2026-10-18T10:00:00Z"):
    digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + password.encode()).digest()).decode()
    return ('<wsse:Security xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" '
            'xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">'
            f'<wsse:UsernameToken><wsse:Username>{user}</wsse:Username>'
            '<wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">'
            f'{digest}</wsse:Password><wsse:Nonce>{base64.b64encode(nonce).decode()}</wsse:Nonce>'
            f'<wsu:Created>{created}</wsu:Created></wsse:UsernameToken></wsse:Security>')


def subcodes(root):
    """The fault subcode chain, e.g. ["ter:InvalidArgVal", "ter:NoProfile"]."""
    chain, elem = [], find(root, "Code")
    while True:
        elem = next((e for e in elem if e.tag.endswith("}Subcode")), None) if elem is not None else None
        if elem is None:
            return chain
        chain.append(text_of(elem, "Value"))


def status_position(onvif):
    _, root = call(onvif, "<tptz:GetStatus><tptz:ProfileToken>Profile_1</tptz:ProfileToken></tptz:GetStatus>")
    pt, zoom = find(root, "Position", "PanTilt"), find(root, "Position", "Zoom")
    return float(pt.get("x")), float(pt.get("y")), float(zoom.get("x"))


@pytest.fixture
def onvif():
    return OnvifCamera(ViscaCamera(instant=True))


def test_coordinate_mapping_roundtrip():
    assert pan_from_onvif(1) == st.PAN_MAX and pan_from_onvif(-1) == st.PAN_MIN
    assert tilt_from_onvif(1) == st.TILT_MAX and tilt_from_onvif(-1) == st.TILT_MIN
    assert tilt_from_onvif(0) == 0
    for v in (-0.7, 0.0, 0.3):
        assert pan_to_onvif(pan_from_onvif(v)) == pytest.approx(v)
        assert tilt_to_onvif(tilt_from_onvif(v)) == pytest.approx(v)


def test_parse_duration():
    assert parse_duration("PT2S") == 2
    assert parse_duration("PT0.5S") == 0.5
    assert parse_duration("PT1M30S") == 90


def test_capabilities_point_to_services(onvif):
    status, root = call(onvif, '<tds:GetCapabilities><tds:Category>All</tds:Category></tds:GetCapabilities>')
    assert status == 200
    assert text_of(root, "PTZ", "XAddr") == "http://127.0.0.1:8080/onvif/ptz_service"
    assert text_of(root, "Media", "XAddr") == "http://127.0.0.1:8080/onvif/media_service"


def test_profile_has_ptz_configuration_with_zoom(onvif):
    _, root = call(onvif, "<trt:GetProfiles/>")
    profile = find(root, "Profiles")
    assert profile.get("token") == "Profile_1"
    assert text_of(profile, "PTZConfiguration", "DefaultContinuousZoomVelocitySpace")


def test_absolute_move_and_status(onvif):
    call(onvif, '<tptz:AbsoluteMove><tptz:ProfileToken>Profile_1</tptz:ProfileToken><tptz:Position>'
                '<tt:PanTilt x="0.5" y="-0.25"/><tt:Zoom x="0.75"/></tptz:Position></tptz:AbsoluteMove>')
    assert status_position(onvif) == pytest.approx((0.5, -0.25, 0.75))
    assert onvif.state.position()[:3] == (1224, -108, 0x3000)


def test_continuous_move_and_stop():
    onvif = OnvifCamera(ViscaCamera())
    call(onvif, '<tptz:ContinuousMove><tptz:ProfileToken>Profile_1</tptz:ProfileToken><tptz:Velocity>'
                '<tt:PanTilt x="1" y="-0.5"/><tt:Zoom x="0.5"/></tptz:Velocity></tptz:ContinuousMove>')
    onvif.state.tick(0.5)
    x, y, z = status_position(onvif)
    assert x > 0 and y < 0 and z > 0
    call(onvif, "<tptz:Stop><tptz:ProfileToken>Profile_1</tptz:ProfileToken>"
                "<tptz:PanTilt>true</tptz:PanTilt><tptz:Zoom>true</tptz:Zoom></tptz:Stop>")
    before = onvif.state.position()
    onvif.state.tick(0.5)
    assert onvif.state.position() == before


def test_continuous_move_stops_itself_after_timeout():
    async def run():
        onvif = OnvifCamera(ViscaCamera())
        call(onvif, '<tptz:ContinuousMove><tptz:ProfileToken>Profile_1</tptz:ProfileToken><tptz:Velocity>'
                    '<tt:PanTilt x="0.5" y="0"/></tptz:Velocity><tptz:Timeout>PT0.1S</tptz:Timeout>'
                    '</tptz:ContinuousMove>')
        assert onvif.state.pan_velocity > 0
        await asyncio.sleep(0.2)
        return onvif.state.pan_velocity

    assert asyncio.run(run()) == 0


def test_repeated_continuous_move_extends_timeout():
    async def run():
        onvif = OnvifCamera(ViscaCamera())
        move = ('<tptz:ContinuousMove><tptz:ProfileToken>Profile_1</tptz:ProfileToken><tptz:Velocity>'
                '<tt:PanTilt x="0.5" y="0"/></tptz:Velocity><tptz:Timeout>PT0.2S</tptz:Timeout>'
                '</tptz:ContinuousMove>')
        call(onvif, move)
        await asyncio.sleep(0.15)
        call(onvif, move)  # like the web UI repeating while the button is held
        await asyncio.sleep(0.15)
        return onvif.state.pan_velocity

    assert asyncio.run(run()) > 0


def test_relative_move_and_home(onvif):
    call(onvif, '<tptz:RelativeMove><tptz:ProfileToken>Profile_1</tptz:ProfileToken><tptz:Translation>'
                '<tt:PanTilt x="0.1" y="0.2"/></tptz:Translation></tptz:RelativeMove>')
    assert status_position(onvif)[:2] == pytest.approx((0.1, 0.2))
    call(onvif, "<tptz:GotoHomePosition><tptz:ProfileToken>Profile_1</tptz:ProfileToken></tptz:GotoHomePosition>")
    assert status_position(onvif)[:2] == (0, 0)


def test_presets_shared_with_visca(onvif):
    onvif.camera.handle(parse_hex("81 01 06 02 18 14 00 01 00 00 00 00 00 00 FF"))
    _, root = call(onvif, "<tptz:SetPreset><tptz:ProfileToken>Profile_1</tptz:ProfileToken>"
                          "<tptz:PresetName>Altar</tptz:PresetName></tptz:SetPreset>")
    token = text_of(root, "PresetToken")
    assert token == "0" and onvif.state.presets[0].name == "Altar"

    onvif.camera.handle(parse_hex("81 01 06 04 FF"))
    call(onvif, f"<tptz:GotoPreset><tptz:ProfileToken>Profile_1</tptz:ProfileToken>"
                f"<tptz:PresetToken>{token}</tptz:PresetToken></tptz:GotoPreset>")
    assert onvif.state.position()[0] == 256

    _, root = call(onvif, "<tptz:GetPresets><tptz:ProfileToken>Profile_1</tptz:ProfileToken></tptz:GetPresets>")
    assert text_of(root, "Preset", "Name") == "Altar"

    call(onvif, "<tptz:RemovePreset><tptz:ProfileToken>Profile_1</tptz:ProfileToken>"
                "<tptz:PresetToken>1</tptz:PresetToken></tptz:RemovePreset>")
    status, root = call(onvif, "<tptz:GotoPreset><tptz:ProfileToken>Profile_1</tptz:ProfileToken>"
                               "<tptz:PresetToken>1</tptz:PresetToken></tptz:GotoPreset>")
    assert status == 400 and subcodes(root) == ["ter:InvalidArgVal", "ter:NoToken"]


def test_camera_without_absolute_move():
    onvif = OnvifCamera(ViscaCamera(instant=True), absolute=False)
    _, node = call(onvif, "<tptz:GetNode><tptz:NodeToken>PTZNode_1</tptz:NodeToken></tptz:GetNode>")
    assert find(node, "SupportedPTZSpaces", "AbsolutePanTiltPositionSpace") is None
    assert find(node, "SupportedPTZSpaces", "ContinuousPanTiltVelocitySpace") is not None
    _, profiles = call(onvif, "<trt:GetProfiles/>")
    assert find(profiles, "Profiles", "PTZConfiguration", "DefaultAbsolutePantTiltPositionSpace") is None
    status, _ = call(onvif, "<tptz:AbsoluteMove><tptz:ProfileToken>Profile_1</tptz:ProfileToken>"
                            '<tptz:Position><tt:PanTilt x="0.5" y="0"/></tptz:Position></tptz:AbsoluteMove>')
    assert status == 500
    status, root = call(onvif, "<tptz:SetPreset><tptz:ProfileToken>Profile_1</tptz:ProfileToken></tptz:SetPreset>")
    assert status == 200 and text_of(root, "Body", "SetPresetResponse", "PresetToken")


def test_unknown_profile_and_action_are_faults(onvif):
    status, root = call(onvif, "<tptz:GetStatus><tptz:ProfileToken>nope</tptz:ProfileToken></tptz:GetStatus>")
    assert status == 400 and subcodes(root) == ["ter:InvalidArgVal", "ter:NoProfile"]
    assert text_of(root, "Code", "Value") == "s:Sender"
    status, root = call(onvif, "<tptz:SendAuxiliaryCommand/>")
    assert status == 500 and subcodes(root) == ["ter:ActionNotSupported"]
    assert text_of(root, "Code", "Value") == "s:Receiver"


def test_digest_authentication():
    onvif = OnvifCamera(ViscaCamera(), username="admin", password="secret", auth="wsse")
    # only WS-UsernameToken: missing credentials are a SOAP fault (Core spec 5.9.1)
    status, root = call(onvif, "<trt:GetProfiles/>")
    assert status == 400 and subcodes(root) == ["ter:NotAuthorized"]
    assert call(onvif, "<trt:GetProfiles/>", username_token("admin", "wrong"))[0] == 400
    assert call(onvif, "<trt:GetProfiles/>", username_token("admin", "secret"))[0] == 200
    # GetCapabilities and GetSystemDateAndTime work before authentication.
    assert call(onvif, "<tds:GetCapabilities/>")[0] == 200
    assert call(onvif, "<tds:GetSystemDateAndTime/>")[0] == 200


def free_port(kind=socket.SOCK_STREAM):
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get_health(port, path="/health", user=None, password=None):
    url = f"http://127.0.0.1:{port}{path}"
    handlers = [urllib.request.ProxyHandler({})]
    if user is not None:
        manager = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        manager.add_password(None, f"http://127.0.0.1:{port}/", user, password)
        handlers.append(urllib.request.HTTPDigestAuthHandler(manager))
    request = urllib.request.Request(url, headers={"Connection": "close"})
    try:
        response = urllib.request.build_opener(*handlers).open(request, timeout=3)
    except urllib.error.HTTPError as err:
        response = err
    with response:
        return response.status, response.headers, response.read()


@pytest.fixture
def health_network(monkeypatch):
    eth0 = InterfaceInfo("eth0")
    eth0.add_ipv4("192.0.2.10", "255.255.255.0")
    interfaces = {"eth0": eth0}
    monkeypatch.setattr("ptzsim.onvif.get_hostname_and_fqdn",
                        lambda: ("camera", "camera.example.test"))
    monkeypatch.setattr("ptzsim.onvif.get_all_interfaces_detailed", lambda: interfaces)
    return interfaces


def test_http_server_keep_alive():
    async def run():
        onvif = OnvifCamera(ViscaCamera(instant=True))
        port = free_port()
        await serve_onvif(onvif, "127.0.0.1", port)

        def talk():
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            results = []
            for body in ("<tds:GetCapabilities/>", "<trt:GetProfiles/>"):
                conn.request("POST", "/onvif/device_service", SOAP.format(header="", body=body),
                             {"Content-Type": "application/soap+xml"})
                response = conn.getresponse()
                results.append((response.status, response.read()))
            conn.close()
            return results

        return await asyncio.get_running_loop().run_in_executor(None, talk)

    results = asyncio.run(run())
    assert [s for s, _ in results] == [200, 200]
    assert b"ptz_service" in results[0][1] and b"Profile_1" in results[1][1]


@pytest.mark.parametrize("path", ["/health", "/"])
def test_health_lists_main_interface_first(monkeypatch, path):
    interfaces = {}
    for i in range(12):
        bridge = InterfaceInfo(f"br-{i:02d}")
        bridge.add_ipv4(f"172.{18 + i}.0.1", "255.255.0.0")
        interfaces[bridge.name] = bridge
    eth0 = InterfaceInfo("eth0")
    eth0.add_ipv4("172.28.67.216", "255.255.240.0")
    interfaces["eth0"] = eth0
    monkeypatch.setattr("ptzsim.onvif.get_all_interfaces_detailed", lambda: interfaces)

    async def run():
        server = await serve_onvif(OnvifCamera(ViscaCamera(instant=True)), "127.0.0.1", 0)
        async with server:
            port = server.sockets[0].getsockname()[1]
            return await asyncio.get_running_loop().run_in_executor(None, get_health, port, path)

    status, _, payload = asyncio.run(run())
    health = json.loads(payload)
    assert status == 200 and health["status"] == "ok"
    assert health["interfaces"][0] == {"name": "eth0", "ipv4": ["172.28.67.216"], "ipv6": []}


@pytest.mark.parametrize("path", ["/health", "/"])
@pytest.mark.parametrize("auth", ["both", "digest", "wsse"])
def test_health_with_credentials_exposes_only_availability(health_network, auth, path):
    async def run():
        onvif = OnvifCamera(ViscaCamera(), name="private-camera",
                            username="admin", password="secret", auth=auth)
        server = await serve_onvif(onvif, "127.0.0.1", 0)
        async with server:
            port = server.sockets[0].getsockname()[1]
            return await asyncio.get_running_loop().run_in_executor(None, get_health, port, path)

    status, _, payload = asyncio.run(run())
    assert status == 200
    assert json.loads(payload) == {"status": "ok"}


@pytest.mark.parametrize("path", ["/health", "/"])
@pytest.mark.parametrize("auth", ["both", "digest", "wsse"])
def test_health_details_require_supported_digest_authentication(health_network, auth, path):
    async def run():
        onvif = OnvifCamera(ViscaCamera(), username="admin", password="secret", auth=auth)
        server = await serve_onvif(onvif, "127.0.0.1", 0)
        async with server:
            port = server.sockets[0].getsockname()[1]

            def requests():
                return [get_health(port, path + "?details=1", user, password)
                        for user, password in ((None, None), ("admin", "wrong"),
                                               ("admin", "secret"))]

            return await asyncio.get_running_loop().run_in_executor(None, requests)

    responses = asyncio.run(run())
    if auth == "wsse":
        assert [status for status, _, _ in responses] == [403, 403, 403]
        assert all("error" in json.loads(payload) for _, _, payload in responses)
    else:
        assert [status for status, _, _ in responses] == [401, 401, 200]
        assert all(headers["WWW-Authenticate"].startswith("Digest ")
                   for _, headers, _ in responses[:2])
        health = json.loads(responses[2][2])
        assert health["hostname"] == "camera"
        assert health["fqdn"] == "camera.example.test"
        assert health["interfaces"] == [{"name": "eth0", "ipv4": ["192.0.2.10"], "ipv6": []}]
    assert all(b"camera.example.test" not in payload and b"192.0.2.10" not in payload
               for status, _, payload in responses if status != 200)


@pytest.mark.parametrize("query", ["details=", "details=invalid", "details=1&details=1"])
def test_health_rejects_invalid_details_query(health_network, query):
    async def run():
        server = await serve_onvif(OnvifCamera(ViscaCamera()), "127.0.0.1", 0)
        async with server:
            port = server.sockets[0].getsockname()[1]
            return await asyncio.get_running_loop().run_in_executor(
                None, get_health, port, "/health?" + query,
            )

    status, _, payload = asyncio.run(run())
    assert status == 400
    assert "error" in json.loads(payload)


@pytest.mark.parametrize("lookup", ["hostname", "interfaces"])
def test_health_lookup_does_not_delay_continuous_move_timeout(monkeypatch, health_network, lookup):
    onvif = OnvifCamera(ViscaCamera())
    stopped_during_lookup = []

    def slow_lookup():
        time.sleep(0.25)
        stopped_during_lookup.append(onvif.state.pan_velocity == 0)
        time.sleep(0.15)
        return ("camera", "camera.example.test") if lookup == "hostname" else health_network

    target = "get_hostname_and_fqdn" if lookup == "hostname" else "get_all_interfaces_detailed"
    monkeypatch.setattr(f"ptzsim.onvif.{target}", slow_lookup)

    async def run():
        server = await serve_onvif(onvif, "127.0.0.1", 0)
        async with server:
            port = server.sockets[0].getsockname()[1]
            status, _ = call(
                onvif, '<tptz:ContinuousMove><tptz:ProfileToken>Profile_1</tptz:ProfileToken>'
                '<tptz:Velocity><tt:PanTilt x="0.5" y="0"/></tptz:Velocity>'
                '<tptz:Timeout>PT0.1S</tptz:Timeout></tptz:ContinuousMove>',
            )
            assert status == 200 and onvif.state.pan_velocity > 0
            return await asyncio.get_running_loop().run_in_executor(None, get_health, port)

    status, _, payload = asyncio.run(run())
    assert status == 200 and json.loads(payload)["status"] == "ok"
    assert stopped_during_lookup == [True]


PROBE = ('<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope" '
         'xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
         'xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" '
         'xmlns:dn="http://www.onvif.org/ver10/network/wsdl"><e:Header>'
         '<w:MessageID>uuid:probe-1</w:MessageID>'
         '<w:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action></e:Header>'
         '<e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body></e:Envelope>')


def test_ws_discovery_probe_match():
    async def run():
        onvif = OnvifCamera(ViscaCamera(), name="Kamera Links")
        port = free_port(socket.SOCK_DGRAM)
        transport = await serve_discovery(onvif, 8080, port=port, multicast=False)

        def probe():
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(2)
                s.sendto(PROBE.encode(), ("127.0.0.1", port))
                return s.recv(8192)

        try:
            return await asyncio.get_running_loop().run_in_executor(None, probe)
        finally:
            transport.close()

    root = ET.fromstring(asyncio.run(run()))
    assert text_of(root, "RelatesTo") == "uuid:probe-1"
    assert text_of(root, "Types").split() == ["dn:NetworkVideoTransmitter", "tds:Device"]
    sequence = find(root, "Header", "AppSequence")
    assert sequence is not None and sequence.get("InstanceId") and sequence.get("MessageNumber")
    assert text_of(root, "XAddrs") == "http://127.0.0.1:8080/onvif/device_service"
    assert "onvif://www.onvif.org/name/Kamera%20Links" in text_of(root, "Scopes").split()




@pytest.mark.skipif(not os.environ.get("PTZSIM_ONVIF_CLIENT"),
                    reason="set PTZSIM_ONVIF_CLIENT=1 with onvif-zeep-async installed")
def test_with_real_onvif_client():
    """Interop check with the onvif-zeep(-async) client library."""
    from onvif import ONVIFCamera

    async def run():
        camera = ViscaCamera()
        sim = Simulator(camera, tick_interval=0.01)
        ticker = asyncio.ensure_future(sim.run())
        port = free_port()
        await serve_onvif(OnvifCamera(camera, username="admin", password="secret"), "127.0.0.1", port)
        client = ONVIFCamera("127.0.0.1", port, "admin", "secret")
        try:
            await client.update_xaddrs()
            media = await client.create_media_service()
            ptz = await client.create_ptz_service()
            profile = (await media.GetProfiles())[0]
            await ptz.ContinuousMove({"ProfileToken": profile.token, "Timeout": "PT2S",
                                      "Velocity": {"PanTilt": {"x": 0.5, "y": 0.5}, "Zoom": {"x": 0.5}}})
            await asyncio.sleep(0.3)
            await ptz.Stop({"ProfileToken": profile.token, "PanTilt": True, "Zoom": True})
            moved = (await ptz.GetStatus({"ProfileToken": profile.token})).Position
            await ptz.AbsoluteMove({"ProfileToken": profile.token,
                                    "Position": {"PanTilt": {"x": -0.5, "y": 0.1}, "Zoom": {"x": 0.2}}})
            await asyncio.sleep(2.5)
            final = await ptz.GetStatus({"ProfileToken": profile.token})
            return moved, final
        finally:
            await client.close()
            ticker.cancel()

    moved, final = asyncio.run(run())
    assert moved.PanTilt.x > 0 and moved.PanTilt.y > 0 and moved.Zoom.x > 0
    assert (final.Position.PanTilt.x, final.Position.PanTilt.y, final.Position.Zoom.x) == \
        pytest.approx((-0.5, 0.1, 0.2))
    assert final.MoveStatus.PanTilt == "IDLE"
