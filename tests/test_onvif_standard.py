# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Behaviour required by the ONVIF Core and PTZ service specifications (26.06)."""

import asyncio
import socket
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

import pytest

from ptzsim import state as st
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
    # PTZ spec 25.12, 5.4.1: an explicit PresetToken must name an existing preset
    (f"<tptz:SetPreset>{P}<tptz:PresetToken>42</tptz:PresetToken></tptz:SetPreset>",
     ["ter:InvalidArgVal", "ter:NoToken"]),
    # 5.3.1-5.3.3, 5.4.3: spaces the node does not support
    (f'<tptz:AbsoluteMove>{P}<tptz:Position><tt:PanTilt x="0" y="0" '
     'space="http://www.onvif.org/ver10/tptz/PanTiltSpaces/SphericalPositionSpaceDegrees"/>'
     "</tptz:Position></tptz:AbsoluteMove>", ["ter:InvalidArgVal", "ter:SpaceNotSupported"]),
    (f'<tptz:RelativeMove>{P}<tptz:Translation><tt:Zoom x="0.1" '
     'space="http://www.onvif.org/ver10/tptz/ZoomSpaces/PositionGenericSpace"/>'
     "</tptz:Translation></tptz:RelativeMove>", ["ter:InvalidArgVal", "ter:SpaceNotSupported"]),
    (f'<tptz:ContinuousMove>{P}<tptz:Velocity><tt:PanTilt x="0.1" y="0" '
     'space="http://www.onvif.org/ver10/tptz/PanTiltSpaces/TranslationGenericSpace"/>'
     "</tptz:Velocity></tptz:ContinuousMove>", ["ter:InvalidArgVal", "ter:SpaceNotSupported"]),
    (f'<tptz:AbsoluteMove>{P}<tptz:Position><tt:Zoom x="0.5"/></tptz:Position><tptz:Speed>'
     '<tt:Zoom x="0.5" space="http://www.onvif.org/ver10/tptz/ZoomSpaces/VelocityGenericSpace"/>'
     "</tptz:Speed></tptz:AbsoluteMove>", ["ter:InvalidArgVal", "ter:SpaceNotSupported"]),
    # 5.3.2: translation outside the generic translation space
    (f'<tptz:RelativeMove>{P}<tptz:Translation><tt:PanTilt x="1.5" y="0"/></tptz:Translation>'
     "</tptz:RelativeMove>", ["ter:InvalidArgVal", "ter:InvalidTranslation"]),
    # 5.3.1, 5.3.2, 5.5.1: speed outside the generic speed space [0, 1]
    (f'<tptz:AbsoluteMove>{P}<tptz:Position><tt:Zoom x="0.5"/></tptz:Position>'
     '<tptz:Speed><tt:Zoom x="2"/></tptz:Speed></tptz:AbsoluteMove>', ["ter:InvalidArgVal", "ter:InvalidSpeed"]),
    (f'<tptz:RelativeMove>{P}<tptz:Translation><tt:Zoom x="0.1"/></tptz:Translation>'
     '<tptz:Speed><tt:PanTilt x="-0.5" y="0.5"/></tptz:Speed></tptz:RelativeMove>',
     ["ter:InvalidArgVal", "ter:InvalidSpeed"]),
    (f'<tptz:GotoHomePosition>{P}<tptz:Speed><tt:PanTilt x="1.2" y="1"/></tptz:Speed></tptz:GotoHomePosition>',
     ["ter:InvalidArgVal", "ter:InvalidSpeed"]),
])
def test_fault_chains(onvif, body, chain):
    status, root = call(onvif, body)
    assert status == 400 and text_of(root, "Code", "Value") == "s:Sender"
    assert subcodes(root) == chain


def test_goto_preset_checks_speed_and_space(onvif):
    _, root = call(onvif, f"<tptz:SetPreset>{P}</tptz:SetPreset>")
    token = text_of(root, "Body", "SetPresetResponse", "PresetToken")
    goto = f"<tptz:GotoPreset>{P}<tptz:PresetToken>{token}</tptz:PresetToken>"
    status, root = call(onvif, goto + '<tptz:Speed><tt:PanTilt x="3" y="1"/></tptz:Speed></tptz:GotoPreset>')
    assert status == 400 and subcodes(root) == ["ter:InvalidArgVal", "ter:InvalidSpeed"]
    status, root = call(onvif, goto + '<tptz:Speed><tt:Zoom x="1" space="urn:unknown"/></tptz:Speed></tptz:GotoPreset>')
    assert status == 400 and subcodes(root) == ["ter:InvalidArgVal", "ter:SpaceNotSupported"]
    # an existing token updates the preset; the referenced default spaces are accepted
    status, _ = call(onvif, f"<tptz:SetPreset>{P}<tptz:PresetToken>{token}</tptz:PresetToken></tptz:SetPreset>")
    assert status == 200
    status, _ = call(onvif, goto + '<tptz:Speed><tt:PanTilt x="0.5" y="0.5" '
                     'space="http://www.onvif.org/ver10/tptz/PanTiltSpaces/GenericSpeedSpace"/></tptz:Speed>'
                     "</tptz:GotoPreset>")
    assert status == 200


def test_goto_home_uses_the_requested_speed():
    onvif = OnvifCamera(ViscaCamera())
    onvif.state.pan = 1000.0
    call(onvif, f'<tptz:GotoHomePosition>{P}<tptz:Speed><tt:PanTilt x="0.5" y="0.5"/></tptz:Speed>'
                "</tptz:GotoHomePosition>")
    slow = onvif.state.pan_target[1]
    call(onvif, f"<tptz:GotoHomePosition>{P}</tptz:GotoHomePosition>")
    assert slow < onvif.state.pan_target[1]


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
        # Python 3.8: urllib's own "digest auth failed" error has no body to read
        return err.code, err.headers, err.read() if err.fp is not None else b""


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


# ------------------------------------------------ review fixes (Core 26.06, Imaging 18.12)
def test_imaging_stop_stops_only_focus_not_the_ptz_unit():
    onvif = OnvifCamera(ViscaCamera())
    call(onvif, f'<tptz:ContinuousMove>{P}<tptz:Velocity><tt:PanTilt x="0.5" y="0"/></tptz:Velocity>'
                "</tptz:ContinuousMove>")
    call(onvif, f"<timg:Move {IMG_NS}>{SOURCE}<timg:Focus><tt:Continuous><tt:Speed>0.5</tt:Speed>"
                "</tt:Continuous></timg:Focus></timg:Move>")
    assert onvif.state.focus_velocity != 0
    status, root = call(onvif, f"<timg:Stop {IMG_NS}>{SOURCE}</timg:Stop>")
    assert status == 200 and find(root, "Body", "StopResponse") is not None
    assert onvif.state.focus_velocity == 0 and onvif.state.focus_target is None
    assert onvif.state.pan_velocity != 0  # imaging Stop (focus) must not stop the PTZ unit
    status, root = call(onvif, f"<timg:GetStatus {IMG_NS}>{SOURCE}</timg:GetStatus>")
    response = find(root, "Body")[0]
    assert status == 200 and response.tag == "{http://www.onvif.org/ver20/imaging/wsdl}GetStatusResponse"


def test_imaging_move_options_advertise_all_focus_moves(onvif):
    status, root = call(onvif, f"<timg:GetMoveOptions {IMG_NS}>{SOURCE}</timg:GetMoveOptions>")
    assert status == 200
    options = find(root, "MoveOptions")
    assert options is not None
    for kind, value_tag, low, high in (("Absolute", "Position", "0", "1"),
                                       ("Relative", "Distance", "-1", "1"),
                                       ("Continuous", "Speed", "-1", "1")):
        elem = find(options, kind)
        assert elem is not None, kind
        assert text_of(elem, value_tag, "Min") == low and text_of(elem, value_tag, "Max") == high
    assert find(options, "Absolute", "Speed", "Max") is not None


def test_imaging_focus_absolute_move(onvif):
    # 0 = infinity (VISCA FOCUS_MIN), 1 = closest (FOCUS_MAX); the fixture is instant
    status, _ = call(onvif, f"<timg:Move {IMG_NS}>{SOURCE}<timg:Focus><tt:Absolute>"
                            "<tt:Position>1</tt:Position></tt:Absolute></timg:Focus></timg:Move>")
    assert status == 200 and onvif.state.focus == st.FOCUS_MAX
    assert onvif.state.autofocus is False  # imaging spec 5.3.1: Move turns autofocus off
    _, root = call(onvif, f"<timg:GetStatus {IMG_NS}>{SOURCE}</timg:GetStatus>")
    assert text_of(root, "FocusStatus20", "Position") == "1"
    assert text_of(root, "FocusStatus20", "MoveStatus") == "IDLE"


def test_imaging_focus_relative_and_continuous_move(onvif):
    call(onvif, f"<timg:Move {IMG_NS}>{SOURCE}<timg:Focus><tt:Absolute>"
                "<tt:Position>0.5</tt:Position></tt:Absolute></timg:Focus></timg:Move>")
    base = onvif.state.focus
    call(onvif, f"<timg:Move {IMG_NS}>{SOURCE}<timg:Focus><tt:Relative>"
                "<tt:Distance>0.1</tt:Distance></tt:Relative></timg:Focus></timg:Move>")
    assert onvif.state.focus == pytest.approx(base + 0.1 * (st.FOCUS_MAX - st.FOCUS_MIN))
    call(onvif, f"<timg:Move {IMG_NS}>{SOURCE}<timg:Focus><tt:Continuous>"
                "<tt:Speed>-0.5</tt:Speed></tt:Continuous></timg:Focus></timg:Move>")
    assert onvif.state.focus_velocity < 0 and onvif.state.focus_target is None
    _, root = call(onvif, f"<timg:GetStatus {IMG_NS}>{SOURCE}</timg:GetStatus>")
    assert text_of(root, "FocusStatus20", "MoveStatus") == "MOVING"
    call(onvif, f"<timg:Move {IMG_NS}>{SOURCE}<timg:Focus><tt:Continuous>"
                "<tt:Speed>0</tt:Speed></tt:Continuous></timg:Focus></timg:Move>")
    assert onvif.state.focus_velocity == 0


def test_imaging_focus_relative_starts_from_the_current_lens_position():
    onvif = OnvifCamera(ViscaCamera())  # not instant: the absolute move is still running
    onvif.state.focus = st.FOCUS_MIN + 0.5 * (st.FOCUS_MAX - st.FOCUS_MIN)
    call(onvif, f"<timg:Move {IMG_NS}>{SOURCE}<timg:Focus><tt:Absolute>"
                "<tt:Position>1</tt:Position></tt:Absolute></timg:Focus></timg:Move>")
    assert onvif.state.focus_target is not None  # absolute move still pending
    call(onvif, f"<timg:Move {IMG_NS}>{SOURCE}<timg:Focus><tt:Relative>"
                "<tt:Distance>-0.1</tt:Distance></tt:Relative></timg:Focus></timg:Move>")
    # spec 5.3.1 "from its current position": base is s.focus, not the pending target
    assert onvif.state.focus_target[0] == pytest.approx(
        st.FOCUS_MIN + 0.5 * (st.FOCUS_MAX - st.FOCUS_MIN) - 0.1 * (st.FOCUS_MAX - st.FOCUS_MIN))


def test_imaging_focus_fault_does_not_disable_autofocus(onvif):
    assert onvif.state.autofocus is True
    status, _ = call(onvif, f"<timg:Move {IMG_NS}>{SOURCE}<timg:Focus><tt:Absolute>"
                            "<tt:Position>1.5</tt:Position></tt:Absolute></timg:Focus></timg:Move>")
    assert status == 400
    assert onvif.state.autofocus is True  # rejected request must not change the focus mode


def test_imaging_move_in_standby_fails():
    onvif = OnvifCamera(ViscaCamera())
    onvif.state.power = False
    status, root = call(onvif, f"<timg:Move {IMG_NS}>{SOURCE}<timg:Focus><tt:Continuous>"
                               "<tt:Speed>0.5</tt:Speed></tt:Continuous></timg:Focus></timg:Move>")
    assert status == 500 and subcodes(root) == ["ter:Action"]
    assert onvif.state.focus_velocity == 0 and onvif.state.autofocus is True


@pytest.mark.parametrize("body, chain", [
    (f"<timg:Move {IMG_NS}><timg:VideoSourceToken>x</timg:VideoSourceToken><timg:Focus>"
     "<tt:Continuous><tt:Speed>0.5</tt:Speed></tt:Continuous></timg:Focus></timg:Move>",
     ["ter:InvalidArgVal", "ter:NoSource"]),
    (f"<timg:Stop {IMG_NS}><timg:VideoSourceToken>x</timg:VideoSourceToken></timg:Stop>",
     ["ter:InvalidArgVal", "ter:NoSource"]),
    (f"<timg:Move {IMG_NS}>{SOURCE}<timg:Focus><tt:Absolute><tt:Position>1.5</tt:Position>"
     "</tt:Absolute></timg:Focus></timg:Move>", ["ter:InvalidArgVal"]),
    (f"<timg:Move {IMG_NS}>{SOURCE}<timg:Focus><tt:Relative><tt:Distance>-2</tt:Distance>"
     "</tt:Relative></timg:Focus></timg:Move>", ["ter:InvalidArgVal"]),
    (f"<timg:Move {IMG_NS}>{SOURCE}<timg:Focus><tt:Continuous><tt:Speed>2</tt:Speed>"
     "</tt:Continuous></timg:Focus></timg:Move>", ["ter:InvalidArgVal"]),
    (f"<timg:Move {IMG_NS}>{SOURCE}</timg:Move>", ["ter:InvalidArgVal"]),
    (f"<timg:Move {IMG_NS}>{SOURCE}<timg:Focus><tt:Absolute><tt:Position>0.5</tt:Position>"
     "<tt:Speed>3</tt:Speed></tt:Absolute></timg:Focus></timg:Move>", ["ter:InvalidArgVal"]),
])
def test_imaging_focus_faults(onvif, body, chain):
    status, root = call(onvif, body)
    assert status == 400 and subcodes(root) == chain


def test_get_wsdl_url_without_login():
    onvif = OnvifCamera(ViscaCamera(), username="admin", password="secret")
    status, root = call(onvif, "<tds:GetWsdlUrl/>")
    assert status == 200 and text_of(root, "WsdlUrl")


def test_failed_http_digest_gets_401():
    onvif = OnvifCamera(ViscaCamera(), username="admin", password="secret")
    port, stop = serve(onvif)
    try:
        assert post(port, "<trt:GetProfiles/>", user="admin", password="wrong")[0] == 401
    finally:
        stop()


def raw_http(port, method, body=b""):
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    conn.request(method, "/onvif/device_service", body=body,
                 headers={"Content-Type": "application/soap+xml", "Connection": "close"})
    response = conn.getresponse()
    response.read()
    conn.close()
    return response.status, response.getheader("WWW-Authenticate")


def test_empty_post_gets_digest_challenge_and_other_methods_405():
    onvif = OnvifCamera(ViscaCamera(), username="admin", password="secret")
    port, stop = serve(onvif)
    try:
        status, challenge = raw_http(port, "POST")
        assert status == 401 and challenge.startswith("Digest ")
        assert raw_http(port, "PUT")[0] == 405
    finally:
        stop()


# ------------------------------------------------ Profile S basics (Core 8.2/8.3, Media 5.2-5.5)
M = "<trt:ProfileToken>Profile_1</trt:ProfileToken>"


def test_profile_has_video_source_encoder_and_ptz(onvif):
    status, root = call(onvif, "<trt:GetProfiles/>")
    profile = find(root, "Profiles")
    names = [e.tag.rsplit("}", 1)[1] for e in profile]
    assert status == 200 and names == ["Name", "VideoSourceConfiguration", "VideoEncoderConfiguration",
                                       "PTZConfiguration"]


def test_remove_and_add_configurations(onvif):
    assert call(onvif, f"<trt:RemoveVideoEncoderConfiguration>{M}</trt:RemoveVideoEncoderConfiguration>")[0] == 200
    status, root = call(onvif, "<trt:GetProfiles/>")
    assert find(root, "VideoEncoderConfiguration") is None
    status, root = call(onvif, f"<trt:GetStreamUri>{M}</trt:GetStreamUri>")
    assert status == 500 and subcodes(root) == ["ter:Action", "ter:IncompleteConfiguration"]
    body = (f"<trt:AddVideoEncoderConfiguration>{M}<trt:ConfigurationToken>VideoEncoderConfig_1"
            "</trt:ConfigurationToken></trt:AddVideoEncoderConfiguration>")
    assert call(onvif, body)[0] == 200
    assert call(onvif, f"<trt:GetStreamUri>{M}</trt:GetStreamUri>")[0] == 200
    status, root = call(onvif, body.replace("VideoEncoderConfig_1", "x"))
    assert status == 400 and subcodes(root) == ["ter:InvalidArgVal", "ter:NoConfig"]


@pytest.mark.parametrize("config, ok", [
    ("<tt:Resolution><tt:Width>320</tt:Width><tt:Height>180</tt:Height></tt:Resolution>", True),
    ("<tt:Resolution><tt:Width>1920</tt:Width><tt:Height>1080</tt:Height></tt:Resolution>", False),
    ("<tt:Quality>11</tt:Quality>", False),
    ("<tt:Encoding>JPEG</tt:Encoding>", False),
])
def test_set_video_encoder_configuration(onvif, config, ok):
    body = (f'<trt:SetVideoEncoderConfiguration><trt:Configuration token="VideoEncoderConfig_1">{config}'
            "</trt:Configuration><trt:ForcePersistence>true</trt:ForcePersistence></trt:SetVideoEncoderConfiguration>")
    status, root = call(onvif, body)
    if ok:
        assert status == 200 and onvif.encoder["width"] == 320
    else:
        assert status == 400 and subcodes(root) == ["ter:InvalidArgVal", "ter:ConfigModify"]


def test_scopes_follow_set_add_remove_and_discovery(onvif):
    status, root = call(onvif, "<tds:GetScopes/>")
    kinds = {text_of(s, "ScopeItem"): text_of(s, "ScopeDef") for s in find(root, "Body")[0]}
    assert kinds["onvif://www.onvif.org/type/ptz"] == "Fixed"
    assert kinds["onvif://www.onvif.org/location/simulator"] == "Configurable"
    call(onvif, "<tds:SetScopes><tds:Scopes>onvif://www.onvif.org/name/Lab</tds:Scopes></tds:SetScopes>")
    call(onvif, "<tds:AddScopes><tds:ScopeItem>onvif://www.onvif.org/location/hall</tds:ScopeItem></tds:AddScopes>")
    assert onvif.configurable_scopes == ["onvif://www.onvif.org/name/Lab", "onvif://www.onvif.org/location/hall"]
    protocol = DiscoveryProtocol(onvif, 8080, advertise_host="10.0.0.9")
    assert "onvif://www.onvif.org/location/hall" in protocol.scopes
    status, root = call(onvif, "<tds:RemoveScopes><tds:ScopeItem>onvif://www.onvif.org/type/ptz</tds:ScopeItem>"
                               "</tds:RemoveScopes>")
    assert status == 400 and subcodes(root) == ["ter:OperationProhibited", "ter:FixedScope"]
    status, root = call(onvif, "<tds:RemoveScopes><tds:ScopeItem>onvif://x/y</tds:ScopeItem></tds:RemoveScopes>")
    assert status == 400 and subcodes(root) == ["ter:InvalidArgVal", "ter:NoScope"]


def test_non_discoverable_ignores_probes():
    protocol = discovery()
    call(protocol.onvif, "<tds:SetDiscoveryMode><tds:DiscoveryMode>NonDiscoverable</tds:DiscoveryMode>"
                         "</tds:SetDiscoveryMode>")
    protocol.datagram_received(probe(), ("10.0.0.1", 5000))
    assert protocol.transport.sent == []
    status, root = call(protocol.onvif, "<tds:GetDiscoveryMode/>")
    assert text_of(root, "DiscoveryMode") == "NonDiscoverable"


def test_device_network_and_users():
    onvif = OnvifCamera(ViscaCamera(), username="admin", password="secret")
    status, root = onvif.handle(SOAP.format(header="", body="<tds:GetHostname/>").encode(), "192.168.1.20:8080")
    assert status == 200  # PRE_AUTH
    _, xml = onvif.handle(SOAP.format(header=username_token("admin", "secret"),
                                      body="<tds:GetNetworkInterfaces/>").encode(), "192.168.1.20:8080")
    assert text_of(ET.fromstring(xml), "Manual", "Address") == "192.168.1.20"
    status, root = call(onvif, "<tds:GetUsers/>", username_token("admin", "secret"))
    assert text_of(root, "User", "Username") == "admin" and text_of(root, "UserLevel") == "Administrator"
    status, root = call(onvif, "<tds:SetHostname><tds:Name>bad name</tds:Name></tds:SetHostname>",
                        username_token("admin", "secret"))
    assert status == 400 and subcodes(root) == ["ter:InvalidArgVal", "ter:InvalidHostname"]


def test_ptz_operations_need_the_ptz_configuration(onvif):
    assert call(onvif, f"<trt:RemovePTZConfiguration>{M}</trt:RemovePTZConfiguration>")[0] == 200
    status, root = call(onvif, f'<tptz:RelativeMove>{P}<tptz:Translation><tt:PanTilt x="0.1" y="0"/>'
                               "</tptz:Translation></tptz:RelativeMove>")
    assert status == 400 and subcodes(root) == ["ter:InvalidArgVal", "ter:NoPTZProfile"]
    assert onvif.state.pan_target is None and onvif.state.pan == 0
    assert call(onvif, f"<trt:GetStreamUri>{M}</trt:GetStreamUri>")[0] == 200
    body = (f"<trt:AddPTZConfiguration>{M}<trt:ConfigurationToken>PTZConfig_1</trt:ConfigurationToken>"
            "</trt:AddPTZConfiguration>")
    assert call(onvif, body)[0] == 200
    assert call(onvif, f"<tptz:GetStatus>{P}</tptz:GetStatus>")[0] == 200


def test_discovery_escapes_configured_scopes():
    protocol = discovery()
    call(protocol.onvif, "<tds:SetScopes><tds:Scopes>onvif://www.onvif.org/location/Lab?a=1&amp;b=2</tds:Scopes>"
                         "</tds:SetScopes>")
    root = ET.fromstring(protocol.probe_match("uuid:1", "10.0.0.9"))
    assert "onvif://www.onvif.org/location/Lab?a=1&b=2" in text_of(root, "Scopes").split()
    _, root = call(protocol.onvif, "<tds:GetScopes/>")
    assert "onvif://www.onvif.org/location/Lab?a=1&b=2" in [text_of(s, "ScopeItem") for s in find(root, "Body")[0]]
