"""Behaviour required by the ONVIF Core and PTZ service specifications (26.06)."""

import asyncio
import socket
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

import pytest

from ptzsim.onvif import DiscoveryProtocol, OnvifCamera, Unauthorized, find, scope_matches, serve_onvif, text_of
from ptzsim.visca import ViscaCamera

from test_onvif import PROBE, SOAP, call, free_port, subcodes, username_token

P = "<tptz:ProfileToken>Profile_1</tptz:ProfileToken>"


@pytest.fixture
def onvif():
    return OnvifCamera(ViscaCamera(instant=True))


# ------------------------------------------------------------------ faults
@pytest.mark.parametrize("body, chain", [
    ("<tptz:GetNode><tptz:NodeToken>x</tptz:NodeToken></tptz:GetNode>", ["ter:InvalidArgVal", "ter:NoEntity"]),
    ("<tptz:GetConfiguration><tptz:PTZConfigurationToken>x</tptz:PTZConfigurationToken>"
     "</tptz:GetConfiguration>", ["ter:InvalidArgVal", "ter:NoConfig"]),
    ("<tptz:GetConfigurationOptions><tptz:ConfigurationToken>x</tptz:ConfigurationToken>"
     "</tptz:GetConfigurationOptions>", ["ter:InvalidArgVal", "ter:NoConfig"]),
    (f"<tptz:GotoPreset>{P}<tptz:PresetToken>9</tptz:PresetToken></tptz:GotoPreset>",
     ["ter:InvalidArgVal", "ter:NoToken"]),
    (f'<tptz:ContinuousMove>{P}<tptz:Velocity><tt:PanTilt x="2" y="0"/></tptz:Velocity></tptz:ContinuousMove>',
     ["ter:InvalidArgVal", "ter:InvalidVelocity"]),
    (f'<tptz:ContinuousMove>{P}<tptz:Velocity><tt:PanTilt x="0.5" y="0"/></tptz:Velocity>'
     "<tptz:Timeout>PT5M</tptz:Timeout></tptz:ContinuousMove>", ["ter:InvalidArgVal", "ter:TimeoutNotSupported"]),
    (f'<tptz:AbsoluteMove>{P}<tptz:Position><tt:Zoom x="1.5"/></tptz:Position></tptz:AbsoluteMove>',
     ["ter:InvalidArgVal", "ter:InvalidPosition"]),
])
def test_fault_chains(onvif, body, chain):
    status, root = call(onvif, body)
    assert status == 400 and text_of(root, "Code", "Value") == "s:Sender"
    assert subcodes(root) == chain


def test_set_preset_while_moving_fails():
    onvif = OnvifCamera(ViscaCamera())
    call(onvif, f'<tptz:ContinuousMove>{P}<tptz:Velocity><tt:PanTilt x="0.5" y="0"/></tptz:Velocity>'
                "</tptz:ContinuousMove>")
    status, root = call(onvif, f"<tptz:SetPreset>{P}</tptz:SetPreset>")
    assert status == 500 and subcodes(root) == ["ter:Action", "ter:MovingPTZ"]
    call(onvif, f"<tptz:Stop>{P}</tptz:Stop>")
    assert call(onvif, f"<tptz:SetPreset>{P}</tptz:SetPreset>")[0] == 200


# -------------------------------------------------------- mandatory calls
@pytest.mark.parametrize("prefix, element", [("tds", "Network"), ("trt", "ProfileCapabilities"),
                                             ("tptz", None)])
def test_get_service_capabilities_per_service(onvif, prefix, element):
    status, root = call(onvif, f"<{prefix}:GetServiceCapabilities/>")
    assert status == 200
    response = find(root, "Body", "GetServiceCapabilitiesResponse")
    assert response.tag.startswith("{http://www.onvif.org/")
    capabilities = find(response, "Capabilities")
    assert capabilities is not None
    if element:
        assert find(capabilities, element) is not None
    else:
        assert capabilities.get("MoveStatus") == "true" and capabilities.get("StatusPosition") == "true"


def test_get_service_capabilities_is_pre_auth():
    onvif = OnvifCamera(ViscaCamera(), username="admin", password="secret")
    assert call(onvif, "<tptz:GetServiceCapabilities/>")[0] == 200


def test_get_services_with_capabilities(onvif):
    _, root = call(onvif, "<tds:GetServices><tds:IncludeCapability>true</tds:IncludeCapability></tds:GetServices>")
    services = [e for e in root.iter() if e.tag.endswith("}Service")]
    assert len(services) == 4 and all(find(s, "Capabilities") is not None for s in services)
    _, root = call(onvif, "<tds:GetServices><tds:IncludeCapability>false</tds:IncludeCapability></tds:GetServices>")
    assert find(root, "Service", "Capabilities") is None


def test_set_configuration(onvif):
    body = ('<tptz:SetConfiguration><tptz:PTZConfiguration token="PTZConfig_1"><tt:Name>PTZ</tt:Name>'
            "<tt:UseCount>1</tt:UseCount><tt:NodeToken>PTZNode_1</tt:NodeToken></tptz:PTZConfiguration>"
            "<tptz:ForcePersistence>true</tptz:ForcePersistence></tptz:SetConfiguration>")
    assert call(onvif, body)[0] == 200
    status, root = call(onvif, body.replace('token="PTZConfig_1"', 'token="other"'))
    assert status == 400 and subcodes(root) == ["ter:InvalidArgVal", "ter:NoConfig"]


def test_omitted_axis_keeps_moving_and_zero_stops(onvif):
    move = f"<tptz:ContinuousMove>{P}<tptz:Velocity>{{}}</tptz:Velocity></tptz:ContinuousMove>"
    call(onvif, move.format('<tt:PanTilt x="0.5" y="0"/>'))
    call(onvif, move.format('<tt:Zoom x="0.5"/>'))  # PanTilt omitted: pan keeps moving (PTZ spec 5.3.3)
    assert onvif.state.pan_velocity > 0 and onvif.state.zoom_velocity > 0
    call(onvif, move.format('<tt:PanTilt x="0" y="0"/>'))  # zero stops that axis
    assert onvif.state.pan_velocity == 0 and onvif.state.zoom_velocity > 0


# ----------------------------------------------------------------- imaging
IMG_NS = 'xmlns:timg="http://www.onvif.org/ver20/imaging/wsdl"'
SOURCE = "<timg:VideoSourceToken>VideoSource_1</timg:VideoSourceToken>"


def test_imaging_white_balance_round_trip(onvif):
    assert call(onvif, f"<timg:GetServiceCapabilities {IMG_NS}/>")[0] == 200
    status, root = call(onvif, f"<timg:GetImagingSettings {IMG_NS}>{SOURCE}</timg:GetImagingSettings>")
    assert status == 200 and text_of(root, "WhiteBalance", "Mode") == "AUTO"
    body = (f"<timg:SetImagingSettings {IMG_NS}>{SOURCE}<timg:ImagingSettings><tt:WhiteBalance>"
            "<tt:Mode>MANUAL</tt:Mode><tt:CrGain>0.5</tt:CrGain><tt:CbGain>1.5</tt:CbGain>"
            "</tt:WhiteBalance></timg:ImagingSettings></timg:SetImagingSettings>")
    assert call(onvif, body)[0] == 200
    assert onvif.state.white_balance == "manual" and (onvif.state.red_gain, onvif.state.blue_gain) == (64, 192)
    status, root = call(onvif, f"<timg:GetImagingSettings {IMG_NS}>{SOURCE}</timg:GetImagingSettings>")
    assert text_of(root, "WhiteBalance", "Mode") == "MANUAL"
    assert text_of(root, "WhiteBalance", "CrGain") == "0.5"


def test_imaging_options_and_faults(onvif):
    status, root = call(onvif, f"<timg:GetOptions {IMG_NS}>{SOURCE}</timg:GetOptions>")
    assert status == 200 and float(text_of(root, "WhiteBalance", "YrGain", "Max")) == pytest.approx(255 / 128, abs=1e-6)
    status, root = call(onvif, f"<timg:GetOptions {IMG_NS}><timg:VideoSourceToken>x</timg:VideoSourceToken>"
                               "</timg:GetOptions>")
    assert status == 400 and subcodes(root) == ["ter:InvalidArgVal", "ter:NoSource"]
    body = (f"<timg:SetImagingSettings {IMG_NS}>{SOURCE}<timg:ImagingSettings><tt:WhiteBalance>"
            "<tt:CrGain>5</tt:CrGain></tt:WhiteBalance></timg:ImagingSettings></timg:SetImagingSettings>")
    status, root = call(onvif, body)
    assert status == 400 and subcodes(root) == ["ter:InvalidArgVal", "ter:SettingsInvalid"]
    assert onvif.state.white_balance == "auto"


def test_stream_uri_rejects_unknown_profile(onvif):
    status, root = call(onvif, "<trt:GetStreamUri><trt:ProfileToken>nope</trt:ProfileToken></trt:GetStreamUri>")
    assert status == 400 and subcodes(root) == ["ter:InvalidArgVal", "ter:NoProfile"]
    status, root = call(onvif, "<trt:GetStreamUri><trt:ProfileToken>Profile_1</trt:ProfileToken></trt:GetStreamUri>")
    assert status == 200 and text_of(root, "MediaUri", "Timeout") == "PT0S"


def test_video_source_is_discoverable_for_imaging(onvif):
    status, root = call(onvif, '<trt:GetVideoSources xmlns:trt="http://www.onvif.org/ver10/media/wsdl"/>')
    token = find(root, "VideoSources").get("token")
    assert status == 200 and token == "VideoSource_1"
    body = f"<timg:GetOptions {IMG_NS}><timg:VideoSourceToken>{token}</timg:VideoSourceToken></timg:GetOptions>"
    assert call(onvif, body)[0] == 200


# ------------------------------------------------------- authentication
def serve(onvif):
    """Run the HTTP server in a background loop thread; returns (port, stop)."""
    import threading
    loop = asyncio.new_event_loop()
    port = free_port()
    ready = threading.Event()

    def run():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(serve_onvif(onvif, "127.0.0.1", port))
        ready.set()
        loop.run_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    ready.wait(2)
    return port, lambda: loop.call_soon_threadsafe(loop.stop)


def post(port, body, header="", user=None, password=None):
    data = SOAP.format(header=header, body=body).encode()
    request = urllib.request.Request(f"http://127.0.0.1:{port}/onvif/device_service", data=data,
                                     headers={"Content-Type": "application/soap+xml"})
    handlers = [urllib.request.ProxyHandler({})]  # never via HTTP_PROXY
    if user:
        manager = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        manager.add_password(None, f"http://127.0.0.1:{port}/", user, password)
        handlers.append(urllib.request.HTTPDigestAuthHandler(manager))
    try:
        with urllib.request.build_opener(*handlers).open(request, timeout=3) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as err:
        return err.code, err.headers, err.read()


def test_http_digest_authentication():
    onvif = OnvifCamera(ViscaCamera(), username="admin", password="secret")
    port, stop = serve(onvif)
    try:
        status, headers, _ = post(port, "<trt:GetProfiles/>")
        assert status == 401 and headers["WWW-Authenticate"].startswith("Digest ")
        assert post(port, "<trt:GetProfiles/>", user="admin", password="secret")[0] == 200
        assert post(port, "<trt:GetProfiles/>", user="admin", password="wrong")[0] in (400, 401)
        # WS-UsernameToken is still accepted in the default mode
        assert post(port, "<trt:GetProfiles/>", username_token("admin", "secret"))[0] == 200
    finally:
        stop()


def test_digest_only_ignores_username_token():
    onvif = OnvifCamera(ViscaCamera(), username="admin", password="secret", auth="digest")
    with pytest.raises(Unauthorized):
        call(onvif, "<trt:GetProfiles/>", username_token("admin", "secret"))


# ------------------------------------------------------------ discovery
class FakeTransport:
    def __init__(self):
        self.sent = []

    def sendto(self, data, addr):
        self.sent.append((ET.fromstring(data), addr))

    def is_closing(self):
        return False


def discovery():
    protocol = DiscoveryProtocol(OnvifCamera(ViscaCamera(), name="Cam"), 8080, advertise_host="10.0.0.9")
    protocol.connection_made(FakeTransport())
    return protocol


def probe(types="dn:NetworkVideoTransmitter", scopes=None):
    scope_xml = f"<d:Scopes>{scopes}</d:Scopes>" if scopes is not None else ""
    return (PROBE.replace("<d:Types>dn:NetworkVideoTransmitter</d:Types>", f"<d:Types>{types}</d:Types>{scope_xml}")
            .replace('xmlns:dn=', 'xmlns:tds="http://www.onvif.org/ver10/device/wsdl" xmlns:x="urn:other" xmlns:dn=')
            .encode())


@pytest.mark.parametrize("types, scopes, answered", [
    ("dn:NetworkVideoTransmitter", None, True),
    ("tds:Device", None, True),
    ("", None, True),
    ("x:Printer", None, False),
    ("tds:Device", "onvif://www.onvif.org/name/Cam", True),
    ("tds:Device", "onvif://www.onvif.org/type", True),
    ("tds:Device", "onvif://www.onvif.org/name/Other", False),
    ("tds:Device", "onvif://www.onvif.org/hardware/ptz", False),  # whole segments only
])
def test_probe_matching(types, scopes, answered):
    protocol = discovery()
    protocol.datagram_received(probe(types, scopes), ("10.0.0.1", 5000))
    assert bool(protocol.transport.sent) == answered


def test_scope_matching_rule():
    assert scope_matches("onvif://www.onvif.org", "onvif://www.onvif.org/name/Cam")
    assert scope_matches("ONVIF://WWW.onvif.org/name", "onvif://www.onvif.org/name/Cam")
    assert not scope_matches("onvif://www.onvif.org/name/Ca", "onvif://www.onvif.org/name/Cam")


def test_resolve_match():
    protocol = discovery()
    resolve = PROBE.replace("<d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe>",
                            f"<d:Resolve><w:EndpointReference><w:Address>{protocol.address}</w:Address>"
                            "</w:EndpointReference></d:Resolve>")
    protocol.datagram_received(resolve.encode(), ("10.0.0.1", 5000))
    (root, addr), = protocol.transport.sent
    assert find(root, "Body", "ResolveMatches", "XAddrs").text == "http://10.0.0.9:8080/onvif/device_service"
    protocol.datagram_received(resolve.replace(protocol.address, "urn:uuid:other").encode(), ("10.0.0.1", 5000))
    assert len(protocol.transport.sent) == 1


def test_hello_and_bye_are_multicast_with_increasing_sequence():
    protocol = discovery()
    protocol.hello()
    protocol.bye()
    (hello, addr1), (bye, addr2) = protocol.transport.sent
    assert addr1 == addr2 == ("239.255.255.250", 3702)
    assert find(hello, "Body", "Hello", "Types").text.split() == ["dn:NetworkVideoTransmitter", "tds:Device"]
    assert find(bye, "Body", "Bye", "Address").text == protocol.address
    numbers = [int(find(m, "AppSequence").get("MessageNumber")) for m in (hello, bye)]
    assert numbers == [1, 2]


def test_broken_datagram_is_ignored():
    protocol = discovery()
    protocol.datagram_received(b"<not xml", ("10.0.0.1", 5000))
    assert protocol.transport.sent == []
