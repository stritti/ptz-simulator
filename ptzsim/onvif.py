"""ONVIF PTZ camera: SOAP services (Device, Media, PTZ) and a WS-Discovery responder.

All ONVIF positions use the generic spaces: pan/tilt in [-1, 1], zoom in [0, 1].
They are mapped linearly onto the same :class:`CameraState` the VISCA side uses,
so both protocols control one camera.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import logging
import re
import socket
import struct
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Callable, Dict, Optional, Tuple
from xml.sax.saxutils import escape

from . import state as st
from .visca import ViscaCamera

log = logging.getLogger("ptzsim")

NS = {
    "s": "http://www.w3.org/2003/05/soap-envelope",
    "tds": "http://www.onvif.org/ver10/device/wsdl",
    "trt": "http://www.onvif.org/ver10/media/wsdl",
    "tptz": "http://www.onvif.org/ver20/ptz/wsdl",
    "tt": "http://www.onvif.org/ver10/schema",
    "ter": "http://www.onvif.org/ver10/error",
    "wsse": "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd",
    "wsu": "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd",
}
SPACE = "http://www.onvif.org/ver10/tptz"
PT_POSITION_SPACE = f"{SPACE}/PanTiltSpaces/PositionGenericSpace"
PT_TRANSLATION_SPACE = f"{SPACE}/PanTiltSpaces/TranslationGenericSpace"
PT_VELOCITY_SPACE = f"{SPACE}/PanTiltSpaces/VelocityGenericSpace"
PT_SPEED_SPACE = f"{SPACE}/PanTiltSpaces/GenericSpeedSpace"
ZOOM_POSITION_SPACE = f"{SPACE}/ZoomSpaces/PositionGenericSpace"
ZOOM_TRANSLATION_SPACE = f"{SPACE}/ZoomSpaces/TranslationGenericSpace"
ZOOM_VELOCITY_SPACE = f"{SPACE}/ZoomSpaces/VelocityGenericSpace"
ZOOM_SPEED_SPACE = f"{SPACE}/ZoomSpaces/ZoomGenericSpeedSpace"

PROFILE_TOKEN = "Profile_1"
PTZ_CONFIG_TOKEN = "PTZConfig_1"
PTZ_NODE_TOKEN = "PTZNode_1"

# Calls a client may make before authenticating (ONVIF core spec "PRE_AUTH").
PRE_AUTH = {"GetSystemDateAndTime", "GetCapabilities", "GetServices", "GetServiceCapabilities", "GetWsdlUrl"}

DEFAULT_CONTINUOUS_TIMEOUT = 5.0  # seconds, used when ContinuousMove has no Timeout
TIMEOUT_RANGE = (0.1, 60.0)  # seconds, advertised in GetConfigurationOptions
AUTH_MODES = ("both", "digest", "wsse")
DIGEST_REALM = "ptzsim"


class Unauthorized(Exception):
    """No credentials although the service needs them and HTTP digest is offered:
    answer HTTP 401 with a digest challenge (Core spec 5.9.1)."""


# ------------------------------------------------------------ coordinates
def pan_to_onvif(pan: float) -> float:
    return pan / st.PAN_MAX


def pan_from_onvif(x: float) -> float:
    return st.clamp(x, -1.0, 1.0) * st.PAN_MAX


# Tilt is mapped piecewise so that ONVIF 0 stays horizontal: [-1, 0] covers the
# range below the horizon, [0, 1] the (larger) range above it.
def tilt_to_onvif(tilt: float) -> float:
    return tilt / st.TILT_MAX if tilt >= 0 else tilt / -st.TILT_MIN


def tilt_from_onvif(y: float) -> float:
    y = st.clamp(y, -1.0, 1.0)
    return y * st.TILT_MAX if y >= 0 else y * -st.TILT_MIN


def zoom_to_onvif(zoom: float) -> float:
    return (zoom - st.ZOOM_MIN) / (st.ZOOM_MAX - st.ZOOM_MIN)


def zoom_from_onvif(z: float) -> float:
    return st.ZOOM_MIN + st.clamp(z, 0.0, 1.0) * (st.ZOOM_MAX - st.ZOOM_MIN)


def parse_duration(text: str) -> float:
    """Parse an xs:duration such as ``PT2S``, ``PT0.5S`` or ``PT1M30S`` into seconds."""
    match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?)?", text.strip())
    if not match:
        raise ValueError(f"bad duration {text!r}")
    days, hours, minutes, seconds = match.groups()
    return (int(days or 0) * 86400 + int(hours or 0) * 3600 + int(minutes or 0) * 60
            + float(seconds or 0))


# ------------------------------------------------------------------ XML
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def find(elem: Optional[ET.Element], *path: str) -> Optional[ET.Element]:
    """Find a descendant by local names, ignoring namespaces."""
    for name in path:
        if elem is None:
            return None
        elem = next((e for e in elem.iter() if e is not elem and _local(e.tag) == name), None)
    return elem


def text_of(elem: Optional[ET.Element], *path: str) -> Optional[str]:
    found = find(elem, *path)
    return found.text.strip() if found is not None and found.text else None


def _f(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".") if value else "0"


def envelope(body: str, header: str = "") -> str:
    xmlns = " ".join(f'xmlns:{k}="{v}"' for k, v in NS.items())
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<s:Envelope {xmlns}>'
            f"<s:Header>{header}</s:Header><s:Body>{body}</s:Body></s:Envelope>")


class OnvifFault(Exception):
    """SOAP 1.2 fault. ``subcode`` is the ONVIF chain below env:Sender/env:Receiver,
    e.g. "ter:InvalidArgVal/ter:NoProfile" (Core spec 5.8.2, PTZ spec fault tables)."""

    def __init__(self, subcode: str, reason: str, sender: bool = True):
        super().__init__(reason)
        self.subcode = subcode
        self.reason = reason
        self.sender = sender

    def xml(self) -> str:
        code = "s:Sender" if self.sender else "s:Receiver"
        subcodes = [c for c in self.subcode.split("/") if c]
        nested = "".join(f"<s:Subcode><s:Value>{c}</s:Value>" for c in subcodes) + "</s:Subcode>" * len(subcodes)
        return (f"<s:Fault><s:Code><s:Value>{code}</s:Value>{nested}</s:Code>"
                f"<s:Reason><s:Text xml:lang=\"en\">{escape(self.reason)}</s:Text></s:Reason></s:Fault>")


def invalid_arg(subcode: str, reason: str) -> OnvifFault:
    """env:Sender / ter:InvalidArgVal / ``subcode``."""
    return OnvifFault(f"ter:InvalidArgVal/{subcode}", reason)


def action_failed(subcode: str, reason: str) -> OnvifFault:
    """env:Receiver / ter:Action / ``subcode``."""
    return OnvifFault(f"ter:Action/{subcode}", reason, sender=False)


# ------------------------------------------------------------- service
class OnvifCamera:
    """Answers ONVIF SOAP requests for one simulated camera."""

    def __init__(self, camera: ViscaCamera, name: str = "PTZ-Simulator",
                 username: Optional[str] = None, password: Optional[str] = None,
                 rtsp_uri: Optional[str] = None, absolute: bool = True, auth: str = "both"):
        if auth not in AUTH_MODES:
            raise ValueError(f"auth must be one of {AUTH_MODES}")
        self.camera = camera
        # "both": HTTP digest (RFC 2617) and WS-UsernameToken, "digest"/"wsse": only one of them
        self.auth = auth
        self._digest_nonces: Dict[str, None] = {}
        # False simulates a camera without AbsoluteMove (only continuous moves and presets)
        self.absolute = absolute
        self.name = name
        self.username = username
        self.password = password
        self.rtsp_uri = rtsp_uri
        self.serial = uuid.uuid5(uuid.NAMESPACE_DNS, name).hex[:12].upper()
        self.endpoint_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"ptzsim:{name}")
        self._stop_timer: Optional[asyncio.TimerHandle] = None
        self._actions: Dict[str, Callable[[ET.Element, str], str]] = {
            "GetSystemDateAndTime": self.get_system_date_and_time,
            "GetCapabilities": self.get_capabilities,
            "GetServices": self.get_services,
            "GetDeviceInformation": self.get_device_information,
            "GetProfiles": self.get_profiles,
            "GetProfile": self.get_profile,
            "GetStreamUri": self.get_stream_uri,
            "GetNodes": self.get_nodes,
            "GetNode": self.get_node,
            "GetConfigurations": self.get_configurations,
            "GetConfiguration": self.get_configuration,
            "GetConfigurationOptions": self.get_configuration_options,
            "SetConfiguration": self.set_configuration,
            "GetStatus": self.get_status,
            "ContinuousMove": self.continuous_move,
            "AbsoluteMove": self.absolute_move,
            "RelativeMove": self.relative_move,
            "Stop": self.stop,
            "GotoHomePosition": self.goto_home,
            "SetHomePosition": self.set_home,
            "GetPresets": self.get_presets,
            "SetPreset": self.set_preset,
            "GotoPreset": self.goto_preset,
            "RemovePreset": self.remove_preset,
        }

    @property
    def state(self) -> st.CameraState:
        return self.camera.state

    # ------------------------------------------------------------- dispatch
    def handle(self, xml_body: bytes, host: str, authorization: Optional[str] = None,
               method: str = "POST", uri: str = "/onvif/device_service") -> Tuple[int, str]:
        """Handle one SOAP request; returns (HTTP status, response XML).

        ``authorization`` is the HTTP Authorization header. Raises :class:`Unauthorized`
        when the HTTP layer has to answer 401 with a digest challenge.
        """
        try:
            root = ET.fromstring(xml_body)
        except ET.ParseError as err:
            self.camera.record("ONVIF", f"invalid XML: {err}", ok=False)
            return 400, envelope(OnvifFault("ter:WellFormed", "invalid XML").xml())
        body = find(root, "Body")
        request = next(iter(body), None) if body is not None else None
        if request is None:
            return 400, envelope(OnvifFault("ter:InvalidArgVal", "empty SOAP body").xml())
        action = _local(request.tag)
        try:
            if action not in PRE_AUTH:
                self._check_auth(root, authorization, method, uri)
            handler = self._actions.get(action)
            if action == "GetServiceCapabilities":
                handler = self._service_capabilities_handler(request)
            if handler is None:
                raise OnvifFault("ter:ActionNotSupported", f"{action} is not supported", sender=False)
            response = handler(request, host)
        except OnvifFault as fault:
            self.camera.record("ONVIF", f"{action}: {fault.reason}", ok=False)
            return (400 if fault.sender else 500), envelope(fault.xml())
        except (TypeError, ValueError) as err:
            self.camera.record("ONVIF", f"{action}: {err}", ok=False)
            return 400, envelope(OnvifFault("ter:InvalidArgVal", str(err)).xml())
        return 200, envelope(response)

    def _check_auth(self, root: ET.Element, authorization: Optional[str], method: str, uri: str) -> None:
        """Core spec 5.9.1, figure 4: HTTP digest first, then WS-UsernameToken."""
        if self.username is None:
            return
        token = find(root, "Security", "UsernameToken")
        http_digest = authorization if authorization and authorization.lower().startswith("digest ") else None
        if self.auth == "wsse":
            http_digest = None
        if self.auth == "digest":
            token = None
        if http_digest is None and token is None:
            if self.auth != "wsse":
                raise Unauthorized()
            raise OnvifFault("ter:NotAuthorized", "authentication required")
        if http_digest is not None:
            self._check_http_digest(http_digest, method, uri)
        if token is not None:
            self._check_username_token(token)

    def digest_challenge(self) -> str:
        """WWW-Authenticate header value for a 401 answer."""
        nonce = uuid.uuid4().hex
        self._digest_nonces[nonce] = None
        while len(self._digest_nonces) > 100:  # keep only recent challenges
            self._digest_nonces.pop(next(iter(self._digest_nonces)))
        return f'Digest realm="{DIGEST_REALM}", qop="auth", algorithm=MD5, nonce="{nonce}"'

    def _check_http_digest(self, header: str, method: str, uri: str) -> None:
        params = {k: a or b for k, a, b in re.findall(r'(\w+)=(?:"([^"]*)"|([^,\s]*))', header[7:])}
        if params.get("username") != self.username or params.get("nonce") not in self._digest_nonces:
            raise OnvifFault("ter:NotAuthorized", "HTTP digest: unknown user or nonce")
        def md5(text: str) -> str:
            return hashlib.md5(text.encode()).hexdigest()
        ha1 = md5(f"{self.username}:{params.get('realm', DIGEST_REALM)}:{self.password}")
        ha2 = md5(f"{method}:{params.get('uri', uri)}")
        if params.get("qop"):
            expected = md5(f"{ha1}:{params['nonce']}:{params.get('nc')}:{params.get('cnonce')}:"
                           f"{params['qop']}:{ha2}")
        else:  # RFC 2069 style
            expected = md5(f"{ha1}:{params['nonce']}:{ha2}")
        if params.get("response") != expected:
            raise OnvifFault("ter:NotAuthorized", "HTTP digest: wrong password")

    def _check_username_token(self, token: ET.Element) -> None:
        user = text_of(token, "Username")
        password = find(token, "Password")
        nonce, created = text_of(token, "Nonce"), text_of(token, "Created")
        if user != self.username or password is None:
            raise OnvifFault("ter:NotAuthorized", "unknown user")
        supplied = (password.text or "").strip()
        if password.get("Type", "").endswith("#PasswordText"):
            ok = supplied == self.password
        else:
            if nonce is None or created is None:  # Core spec 5.9.5: both are required
                raise OnvifFault("ter:NotAuthorized", "digest without nonce/created")
            digest = hashlib.sha1(base64.b64decode(nonce) + created.encode() + self.password.encode())
            ok = base64.b64encode(digest.digest()).decode() == supplied
        if not ok:
            raise OnvifFault("ter:NotAuthorized", "wrong password")

    def _check_profile(self, request: ET.Element, tag: str = "ProfileToken") -> None:
        token = text_of(request, tag)
        if token is not None and token != PROFILE_TOKEN:
            raise invalid_arg("ter:NoProfile", f"unknown profile {token}")

    # ------------------------------------------------------------- device
    def get_system_date_and_time(self, request, host) -> str:
        now = datetime.now(timezone.utc)
        return ("<tds:GetSystemDateAndTimeResponse><tds:SystemDateAndTime>"
                "<tt:DateTimeType>Manual</tt:DateTimeType><tt:DaylightSavings>false</tt:DaylightSavings>"
                "<tt:TimeZone><tt:TZ>UTC0</tt:TZ></tt:TimeZone><tt:UTCDateTime>"
                f"<tt:Time><tt:Hour>{now.hour}</tt:Hour><tt:Minute>{now.minute}</tt:Minute>"
                f"<tt:Second>{now.second}</tt:Second></tt:Time>"
                f"<tt:Date><tt:Year>{now.year}</tt:Year><tt:Month>{now.month}</tt:Month>"
                f"<tt:Day>{now.day}</tt:Day></tt:Date>"
                "</tt:UTCDateTime></tds:SystemDateAndTime></tds:GetSystemDateAndTimeResponse>")

    def get_capabilities(self, request, host) -> str:
        self.camera.record("ONVIF", "GetCapabilities")
        base = f"http://{host}/onvif"
        return ("<tds:GetCapabilitiesResponse><tds:Capabilities>"
                f"<tt:Device><tt:XAddr>{base}/device_service</tt:XAddr></tt:Device>"
                f"<tt:Media><tt:XAddr>{base}/media_service</tt:XAddr><tt:StreamingCapabilities>"
                "<tt:RTPMulticast>false</tt:RTPMulticast><tt:RTP_TCP>true</tt:RTP_TCP>"
                "<tt:RTP_RTSP_TCP>true</tt:RTP_RTSP_TCP></tt:StreamingCapabilities></tt:Media>"
                f"<tt:PTZ><tt:XAddr>{base}/ptz_service</tt:XAddr></tt:PTZ>"
                "</tds:Capabilities></tds:GetCapabilitiesResponse>")

    def get_services(self, request, host) -> str:
        base = f"http://{host}/onvif"
        include = (text_of(request, "IncludeCapability") or "false").lower() == "true"
        services = [("tds", "device_service"), ("trt", "media_service"), ("tptz", "ptz_service")]
        items = "".join(
            f"<tds:Service><tds:Namespace>{NS[prefix]}</tds:Namespace><tds:XAddr>{base}/{path}</tds:XAddr>"
            + (f"<tds:Capabilities>{self._service_capabilities(prefix)}</tds:Capabilities>" if include else "")
            + "<tds:Version><tt:Major>2</tt:Major><tt:Minor>0</tt:Minor></tds:Version></tds:Service>"
            for prefix, path in services)
        return f"<tds:GetServicesResponse>{items}</tds:GetServicesResponse>"

    def _service_capabilities(self, prefix: str) -> str:
        if prefix == "tds":
            return ('<tds:Capabilities><tds:Network/>'
                    f'<tds:Security UsernameToken="{str(self.auth != "digest").lower()}" '
                    f'HttpDigest="{str(self.auth != "wsse").lower()}"/>'
                    '<tds:System DiscoveryResolve="true" DiscoveryBye="true"/></tds:Capabilities>')
        if prefix == "trt":
            return ('<trt:Capabilities><trt:ProfileCapabilities MaximumNumberOfProfiles="1"/>'
                    '<trt:StreamingCapabilities RTP_TCP="true" RTP_RTSP_TCP="true"/></trt:Capabilities>')
        return ('<tptz:Capabilities EFlip="false" Reverse="false" GetCompatibleConfigurations="false" '
                'MoveStatus="true" StatusPosition="true"/>')

    def _service_capabilities_handler(self, request: ET.Element):
        """GetServiceCapabilities exists in every service; the namespace says which one."""
        prefix = {v: k for k, v in NS.items()}.get(request.tag[1:].split("}")[0], "tds")
        if prefix not in ("tds", "trt", "tptz"):
            return None

        def handler(request, host) -> str:
            return (f"<{prefix}:GetServiceCapabilitiesResponse>{self._service_capabilities(prefix)}"
                    f"</{prefix}:GetServiceCapabilitiesResponse>")
        return handler

    def get_device_information(self, request, host) -> str:
        return ("<tds:GetDeviceInformationResponse><tds:Manufacturer>ptzsim</tds:Manufacturer>"
                f"<tds:Model>{escape(self.name)}</tds:Model><tds:FirmwareVersion>0.1.0</tds:FirmwareVersion>"
                f"<tds:SerialNumber>{self.serial}</tds:SerialNumber><tds:HardwareId>ptzsim</tds:HardwareId>"
                "</tds:GetDeviceInformationResponse>")

    # -------------------------------------------------------------- media
    def _profile_xml(self, tag: str = "trt:Profiles") -> str:
        return (f'<{tag} token="{PROFILE_TOKEN}" fixed="true"><tt:Name>{escape(self.name)}</tt:Name>'
                f"{self._configuration_xml('tt:PTZConfiguration')}</{tag}>")

    def get_profiles(self, request, host) -> str:
        self.camera.record("ONVIF", "GetProfiles")
        return f"<trt:GetProfilesResponse>{self._profile_xml()}</trt:GetProfilesResponse>"

    def get_profile(self, request, host) -> str:
        self._check_profile(request)
        return f"<trt:GetProfileResponse>{self._profile_xml('trt:Profile')}</trt:GetProfileResponse>"

    def get_stream_uri(self, request, host) -> str:
        uri = self.rtsp_uri or f"rtsp://{host.split(':')[0]}:554/stream"
        return ("<trt:GetStreamUriResponse><trt:MediaUri>"
                f"<tt:Uri>{escape(uri)}</tt:Uri><tt:InvalidAfterConnect>false</tt:InvalidAfterConnect>"
                "<tt:InvalidAfterReboot>false</tt:InvalidAfterReboot><tt:Timeout>PT0S</tt:Timeout>"
                "</trt:MediaUri></trt:GetStreamUriResponse>")

    # ---------------------------------------------------------- PTZ config
    def _spaces_xml(self) -> str:
        def space2d(tag, uri, low, high):
            return (f"<tt:{tag}><tt:URI>{uri}</tt:URI><tt:XRange><tt:Min>{low}</tt:Min><tt:Max>{high}"
                    f"</tt:Max></tt:XRange><tt:YRange><tt:Min>{low}</tt:Min><tt:Max>{high}</tt:Max>"
                    f"</tt:YRange></tt:{tag}>")

        def space1d(tag, uri, low, high):
            return (f"<tt:{tag}><tt:URI>{uri}</tt:URI><tt:XRange><tt:Min>{low}</tt:Min>"
                    f"<tt:Max>{high}</tt:Max></tt:XRange></tt:{tag}>")

        absolute = (space2d("AbsolutePanTiltPositionSpace", PT_POSITION_SPACE, -1, 1)
                    + space1d("AbsoluteZoomPositionSpace", ZOOM_POSITION_SPACE, 0, 1)) if self.absolute else ""
        return (absolute
                + space2d("RelativePanTiltTranslationSpace", PT_TRANSLATION_SPACE, -1, 1)
                + space1d("RelativeZoomTranslationSpace", ZOOM_TRANSLATION_SPACE, -1, 1)
                + space2d("ContinuousPanTiltVelocitySpace", PT_VELOCITY_SPACE, -1, 1)
                + space1d("ContinuousZoomVelocitySpace", ZOOM_VELOCITY_SPACE, -1, 1)
                + space1d("PanTiltSpeedSpace", PT_SPEED_SPACE, 0, 1)
                + space1d("ZoomSpeedSpace", ZOOM_SPEED_SPACE, 0, 1))

    def _node_xml(self, tag: str) -> str:
        return (f'<{tag} token="{PTZ_NODE_TOKEN}" FixedHomePosition="false"><tt:Name>{escape(self.name)}</tt:Name>'
                f"<tt:SupportedPTZSpaces>{self._spaces_xml()}</tt:SupportedPTZSpaces>"
                f"<tt:MaximumNumberOfPresets>{st.PRESET_COUNT - 1}</tt:MaximumNumberOfPresets>"
                f"<tt:HomeSupported>true</tt:HomeSupported></{tag}>")

    def _configuration_xml(self, tag: str) -> str:
        absolute = (f"<tt:DefaultAbsolutePantTiltPositionSpace>{PT_POSITION_SPACE}</tt:DefaultAbsolutePantTiltPositionSpace>"
                    f"<tt:DefaultAbsoluteZoomPositionSpace>{ZOOM_POSITION_SPACE}</tt:DefaultAbsoluteZoomPositionSpace>"
                    if self.absolute else "")
        return (f'<{tag} token="{PTZ_CONFIG_TOKEN}"><tt:Name>PTZ</tt:Name><tt:UseCount>1</tt:UseCount>'
                f"<tt:NodeToken>{PTZ_NODE_TOKEN}</tt:NodeToken>"
                + absolute
                + f"<tt:DefaultRelativePanTiltTranslationSpace>{PT_TRANSLATION_SPACE}</tt:DefaultRelativePanTiltTranslationSpace>"
                f"<tt:DefaultRelativeZoomTranslationSpace>{ZOOM_TRANSLATION_SPACE}</tt:DefaultRelativeZoomTranslationSpace>"
                f"<tt:DefaultContinuousPanTiltVelocitySpace>{PT_VELOCITY_SPACE}</tt:DefaultContinuousPanTiltVelocitySpace>"
                f"<tt:DefaultContinuousZoomVelocitySpace>{ZOOM_VELOCITY_SPACE}</tt:DefaultContinuousZoomVelocitySpace>"
                f'<tt:DefaultPTZSpeed><tt:PanTilt x="1" y="1" space="{PT_SPEED_SPACE}"/>'
                f'<tt:Zoom x="1" space="{ZOOM_SPEED_SPACE}"/></tt:DefaultPTZSpeed>'
                f"<tt:DefaultPTZTimeout>PT5S</tt:DefaultPTZTimeout></{tag}>")

    def get_nodes(self, request, host) -> str:
        return f"<tptz:GetNodesResponse>{self._node_xml('tptz:PTZNode')}</tptz:GetNodesResponse>"

    def get_node(self, request, host) -> str:
        token = text_of(request, "NodeToken")
        if token != PTZ_NODE_TOKEN:
            raise invalid_arg("ter:NoEntity", f"unknown node {token}")
        return f"<tptz:GetNodeResponse>{self._node_xml('tptz:PTZNode')}</tptz:GetNodeResponse>"

    def get_configurations(self, request, host) -> str:
        return (f"<tptz:GetConfigurationsResponse>{self._configuration_xml('tptz:PTZConfiguration')}"
                "</tptz:GetConfigurationsResponse>")

    @staticmethod
    def _check_config(request: ET.Element, tag: str) -> None:
        token = text_of(request, tag)
        if token != PTZ_CONFIG_TOKEN:
            raise invalid_arg("ter:NoConfig", f"unknown configuration {token}")

    def get_configuration(self, request, host) -> str:
        self._check_config(request, "PTZConfigurationToken")
        return (f"<tptz:GetConfigurationResponse>{self._configuration_xml('tptz:PTZConfiguration')}"
                "</tptz:GetConfigurationResponse>")

    def set_configuration(self, request, host) -> str:
        config = find(request, "PTZConfiguration")
        token = config.get("token") if config is not None else None
        if token != PTZ_CONFIG_TOKEN:
            raise invalid_arg("ter:NoConfig", f"unknown configuration {token}")
        self.camera.record("ONVIF", "SetConfiguration (accepted, not changed)")
        return "<tptz:SetConfigurationResponse/>"

    def get_configuration_options(self, request, host) -> str:
        self._check_config(request, "ConfigurationToken")
        return ("<tptz:GetConfigurationOptionsResponse><tptz:PTZConfigurationOptions>"
                f"<tt:Spaces>{self._spaces_xml()}</tt:Spaces>"
                "<tt:PTZTimeout><tt:Min>PT0.1S</tt:Min><tt:Max>PT60S</tt:Max></tt:PTZTimeout>"
                "</tptz:PTZConfigurationOptions></tptz:GetConfigurationOptionsResponse>")

    # --------------------------------------------------------- PTZ status
    def _vector_xml(self, pan: float, tilt: float, zoom: float) -> str:
        return (f'<tt:PanTilt x="{_f(pan_to_onvif(pan))}" y="{_f(tilt_to_onvif(tilt))}" '
                f'space="{PT_POSITION_SPACE}"/>'
                f'<tt:Zoom x="{_f(zoom_to_onvif(zoom))}" space="{ZOOM_POSITION_SPACE}"/>')

    def get_status(self, request, host) -> str:
        self._check_profile(request)
        s = self.state
        pt_moving = s.pan_target or s.tilt_target or s.pan_velocity or s.tilt_velocity
        zoom_moving = s.zoom_target or s.zoom_velocity
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return ("<tptz:GetStatusResponse><tptz:PTZStatus>"
                f"<tt:Position>{self._vector_xml(s.pan, s.tilt, s.zoom)}</tt:Position>"
                f"<tt:MoveStatus><tt:PanTilt>{'MOVING' if pt_moving else 'IDLE'}</tt:PanTilt>"
                f"<tt:Zoom>{'MOVING' if zoom_moving else 'IDLE'}</tt:Zoom></tt:MoveStatus>"
                f"<tt:UtcTime>{now}</tt:UtcTime></tptz:PTZStatus></tptz:GetStatusResponse>")

    # ----------------------------------------------------------- PTZ moves
    def _require_power(self) -> None:
        if not self.state.power:
            raise OnvifFault("ter:Action", "camera in standby", sender=False)

    def _cancel_timer(self) -> None:
        if self._stop_timer is not None:
            self._stop_timer.cancel()
            self._stop_timer = None

    @staticmethod
    def _xy(elem: Optional[ET.Element]) -> Tuple[Optional[float], Optional[float]]:
        if elem is None:
            return None, None
        x, y = elem.get("x"), elem.get("y")
        return (float(x) if x is not None else None), (float(y) if y is not None else None)

    def _speeds(self, request: ET.Element) -> Tuple[float, float, float]:
        """Return pan speed step, tilt speed step and a zoom factor from <Speed>."""
        sx, sy = self._xy(find(request, "Speed", "PanTilt"))
        sz, _ = self._xy(find(request, "Speed", "Zoom"))
        pan = st.PAN_SPEED_MAX * st.clamp(sx if sx is not None else 1.0, 0.0, 1.0)
        tilt = st.TILT_SPEED_MAX * st.clamp(sy if sy is not None else 1.0, 0.0, 1.0)
        return max(pan, 1.0), max(tilt, 1.0), st.clamp(sz if sz is not None else 1.0, 0.05, 1.0)

    def continuous_move(self, request, host) -> str:
        self._check_profile(request)
        self._require_power()
        s = self.state
        vx, vy = self._xy(find(request, "Velocity", "PanTilt"))
        vz, _ = self._xy(find(request, "Velocity", "Zoom"))
        if any(v is not None and not -1.0 <= v <= 1.0 for v in (vx, vy, vz)):
            raise invalid_arg("ter:InvalidVelocity", "velocity outside the generic space [-1, 1]")
        timeout_text = text_of(request, "Timeout")
        timeout = parse_duration(timeout_text) if timeout_text else DEFAULT_CONTINUOUS_TIMEOUT
        if not TIMEOUT_RANGE[0] <= timeout <= TIMEOUT_RANGE[1]:
            raise invalid_arg("ter:TimeoutNotSupported", f"timeout {timeout:g}s outside PT0.1S..PT60S")
        vx, vy = vx or 0.0, vy or 0.0
        if find(request, "Velocity", "PanTilt") is not None:
            s.pan_target = s.tilt_target = None
            s.pan_velocity = vx * st.PAN_SPEED_MAX * st.PAN_TILT_UNITS_PER_SPEED_STEP
            s.tilt_velocity = vy * st.TILT_SPEED_MAX * st.PAN_TILT_UNITS_PER_SPEED_STEP
        if vz is not None:
            s.zoom_target = None
            s.zoom_velocity = vz * 8 * st.ZOOM_UNITS_PER_SPEED_STEP

        self._cancel_timer()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and timeout > 0:
            self._stop_timer = loop.call_later(timeout, self._timeout_stop)

        parts = [f"pan {vx:+.2f} tilt {vy:+.2f}"] if find(request, "Velocity", "PanTilt") is not None else []
        if vz is not None:
            parts.append(f"zoom {vz:+.2f}")
        self.camera.record("ONVIF", f"ContinuousMove {' '.join(parts)} ({timeout:g}s)")
        return "<tptz:ContinuousMoveResponse/>"

    def _timeout_stop(self) -> None:
        self._stop_timer = None
        s = self.state
        s.pan_velocity = s.tilt_velocity = s.zoom_velocity = 0.0
        self.camera.record("ONVIF", "ContinuousMove timeout, stopped")

    def stop(self, request, host) -> str:
        self._check_profile(request)
        stop_pt = (text_of(request, "PanTilt") or "true").lower() == "true"
        stop_zoom = (text_of(request, "Zoom") or "true").lower() == "true"
        s = self.state
        if stop_pt:
            s.stop_pan_tilt()
        if stop_zoom:
            s.zoom_velocity = 0.0
            s.zoom_target = None
        if stop_pt and stop_zoom:
            self._cancel_timer()
        what = " + ".join(n for n, f in (("pan/tilt", stop_pt), ("zoom", stop_zoom)) if f)
        self.camera.record("ONVIF", f"Stop {what or 'nothing'}")
        return "<tptz:StopResponse/>"

    def _move_to(self, pan: Optional[float], tilt: Optional[float], zoom: Optional[float],
                 speeds: Tuple[float, float, float]) -> None:
        s = self.state
        pan_speed, tilt_speed, zoom_factor = speeds
        if pan is not None or tilt is not None:
            s.move_pan_tilt_to(pan if pan is not None else s.pan,
                               tilt if tilt is not None else s.tilt, pan_speed, tilt_speed)
        if zoom is not None:
            s.zoom_to(zoom)
            s.zoom_target = (s.zoom_target[0], s.zoom_target[1] * zoom_factor)
        if self.camera.instant:
            s.finish_moves()

    def absolute_move(self, request, host) -> str:
        if not self.absolute:
            raise OnvifFault("ter:ActionNotSupported/ter:OptionalActionNotSupported",
                             "AbsoluteMove is not supported", sender=False)
        self._check_profile(request)
        self._require_power()
        self._cancel_timer()
        x, y = self._xy(find(request, "Position", "PanTilt"))
        z, _ = self._xy(find(request, "Position", "Zoom"))
        if any(v is not None and not -1.0 <= v <= 1.0 for v in (x, y)) or (z is not None and not 0.0 <= z <= 1.0):
            raise invalid_arg("ter:InvalidPosition", "position outside the generic space")
        self._move_to(pan_from_onvif(x) if x is not None else None,
                      tilt_from_onvif(y) if y is not None else None,
                      zoom_from_onvif(z) if z is not None else None, self._speeds(request))
        self.camera.record("ONVIF", "AbsoluteMove " + " ".join(
            f"{n} {v:+.3f}" for n, v in (("pan", x), ("tilt", y), ("zoom", z)) if v is not None))
        return "<tptz:AbsoluteMoveResponse/>"

    def relative_move(self, request, host) -> str:
        self._check_profile(request)
        self._require_power()
        self._cancel_timer()
        s = self.state
        dx, dy = self._xy(find(request, "Translation", "PanTilt"))
        dz, _ = self._xy(find(request, "Translation", "Zoom"))
        base_pan = s.pan_target[0] if s.pan_target else s.pan
        base_tilt = s.tilt_target[0] if s.tilt_target else s.tilt
        base_zoom = s.zoom_target[0] if s.zoom_target else s.zoom
        self._move_to(
            base_pan + dx * st.PAN_MAX if dx is not None else None,
            tilt_from_onvif(tilt_to_onvif(base_tilt) + dy) if dy is not None else None,
            base_zoom + dz * (st.ZOOM_MAX - st.ZOOM_MIN) if dz is not None else None,
            self._speeds(request))
        self.camera.record("ONVIF", "RelativeMove " + " ".join(
            f"{n} {v:+.3f}" for n, v in (("pan", dx), ("tilt", dy), ("zoom", dz)) if v is not None))
        return "<tptz:RelativeMoveResponse/>"

    def goto_home(self, request, host) -> str:
        self._check_profile(request)
        self._require_power()
        self._cancel_timer()
        self.state.home()
        if self.camera.instant:
            self.state.finish_moves()
        self.camera.record("ONVIF", "GotoHomePosition")
        return "<tptz:GotoHomePositionResponse/>"

    def set_home(self, request, host) -> str:
        self._check_profile(request)
        self.state.set_home()
        self.camera.record("ONVIF", "SetHomePosition")
        return "<tptz:SetHomePositionResponse/>"

    # ------------------------------------------------------------ presets
    def get_presets(self, request, host) -> str:
        self._check_profile(request)
        items = "".join(
            f'<tptz:Preset token="{n}"><tt:Name>{escape(p.name or f"Preset {n}")}</tt:Name>'
            f"<tt:PTZPosition>{self._vector_xml(p.pan, p.tilt, p.zoom)}</tt:PTZPosition></tptz:Preset>"
            for n, p in sorted(self.state.presets.items()))
        return f"<tptz:GetPresetsResponse>{items}</tptz:GetPresetsResponse>"

    def _preset_number(self, token: Optional[str]) -> int:
        try:
            number = int(token)
        except (TypeError, ValueError):
            raise invalid_arg("ter:NoToken", f"unknown preset {token}")
        if not 0 <= number < st.PRESET_COUNT:
            raise invalid_arg("ter:NoToken", f"unknown preset {token}")
        return number

    def set_preset(self, request, host) -> str:
        self._check_profile(request)
        if self.state.moving:  # PTZ spec 5.4.1: fails while the unit moves
            raise action_failed("ter:MovingPTZ", "preset cannot be set while the camera moves")
        token = text_of(request, "PresetToken")
        if token is None:
            number = self.state.free_preset_number()
            if number is None:
                raise action_failed("ter:TooManyPresets", "no free preset slot")
        else:
            number = self._preset_number(token)
        self.state.save_preset(number, text_of(request, "PresetName"))
        self.camera.record("ONVIF", f"SetPreset {number}")
        return f"<tptz:SetPresetResponse><tptz:PresetToken>{number}</tptz:PresetToken></tptz:SetPresetResponse>"

    def goto_preset(self, request, host) -> str:
        self._check_profile(request)
        self._require_power()
        self._cancel_timer()
        number = self._preset_number(text_of(request, "PresetToken"))
        if not self.state.recall_preset(number):
            raise invalid_arg("ter:NoToken", f"preset {number} not set")
        if self.camera.instant:
            self.state.finish_moves()
        self.camera.record("ONVIF", f"GotoPreset {number}")
        return "<tptz:GotoPresetResponse/>"

    def remove_preset(self, request, host) -> str:
        self._check_profile(request)
        number = self._preset_number(text_of(request, "PresetToken"))
        if number not in self.state.presets:
            raise invalid_arg("ter:NoToken", f"preset {number} not set")
        self.state.clear_preset(number)
        self.camera.record("ONVIF", f"RemovePreset {number}")
        return "<tptz:RemovePresetResponse/>"


# ------------------------------------------------------------ HTTP server
async def serve_onvif(onvif: OnvifCamera, host: str, port: int) -> asyncio.AbstractServer:
    """Minimal HTTP/1.1 server (keep-alive capable) carrying the SOAP services."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        local_ip, local_port = writer.get_extra_info("sockname")[:2]
        try:
            while True:
                request_line = await reader.readline()
                if not request_line:
                    break
                method, path, _ = request_line.decode("latin-1").split(" ", 2)
                headers: Dict[str, str] = {}
                while (line := await reader.readline()) not in (b"\r\n", b"\n", b""):
                    key, _, value = line.decode("latin-1").partition(":")
                    headers[key.strip().lower()] = value.strip()
                body = await reader.readexactly(int(headers.get("content-length", 0) or 0))
                host_header = headers.get("host") or f"{local_ip}:{local_port}"

                extra = ""
                if method == "POST":
                    content_type = "application/soap+xml; charset=utf-8"
                    try:
                        status, payload = onvif.handle(body, host_header, headers.get("authorization"),
                                                       method, path)
                    except Unauthorized:
                        status, payload = 401, ""
                        content_type = "text/plain; charset=utf-8"
                        extra = f"WWW-Authenticate: {onvif.digest_challenge()}\r\n"
                else:
                    status, payload = 200, f"ptzsim ONVIF camera '{onvif.name}'\n"
                    content_type = "text/plain; charset=utf-8"
                data = payload.encode()
                reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized",
                          500: "Internal Server Error"}[status]
                close = headers.get("connection", "").lower() == "close"
                writer.write(
                    f"HTTP/1.1 {status} {reason}\r\nContent-Type: {content_type}\r\n{extra}"
                    f"Content-Length: {len(data)}\r\nConnection: {'close' if close else 'keep-alive'}"
                    f"\r\n\r\n".encode() + data)
                await writer.drain()
                if close:
                    break
        except (ConnectionError, asyncio.IncompleteReadError, ValueError):
            pass
        finally:
            writer.close()

    return await asyncio.start_server(handle, host, port)


# ------------------------------------------------------------ WS-Discovery
DISCOVERY_GROUP = "239.255.255.250"
DISCOVERY_PORT = 3702


def _local_ip_for(peer_ip: str) -> str:
    """The address of this machine as seen from ``peer_ip``."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect((peer_ip, 9))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


WSA = "http://schemas.xmlsoap.org/ws/2004/08/addressing"
WSD = "http://schemas.xmlsoap.org/ws/2005/04/discovery"
WSD_TO = "urn:schemas-xmlsoap-org:ws:2005:04:discovery"
DEVICE_TYPES = {("http://www.onvif.org/ver10/network/wsdl", "NetworkVideoTransmitter"),
                (NS["tds"], "Device")}


def scope_matches(probe_scope: str, device_scope: str) -> bool:
    """rfc3986 matching rule: same scheme and authority, path segments as prefix."""
    def parts(uri: str):
        scheme, _, rest = uri.partition("://")
        authority, _, path = rest.partition("/")
        return scheme.lower(), authority.lower(), [seg for seg in path.split("/") if seg]
    ps, pa, pp = parts(probe_scope)
    ds, da, dp = parts(device_scope)
    return ps == ds and pa == da and dp[:len(pp)] == pp


class DiscoveryProtocol(asyncio.DatagramProtocol):
    """WS-Discovery target service: Hello/Bye, Probe and Resolve (ONVIF Core spec 7)."""

    def __init__(self, onvif: OnvifCamera, http_port: int, advertise_host: Optional[str] = None):
        self.onvif = onvif
        self.http_port = http_port
        self.advertise_host = advertise_host
        self.transport: Optional[asyncio.DatagramTransport] = None
        # AppSequence: InstanceId changes on every start, MessageNumber counts messages
        self.instance_id = int(datetime.now(timezone.utc).timestamp())
        self.message_number = 0

    @property
    def address(self) -> str:
        return f"urn:uuid:{self.onvif.endpoint_uuid}"

    @property
    def scopes(self) -> list:
        name = self.onvif.name.replace(" ", "%20")
        return ["onvif://www.onvif.org/type/ptz", "onvif://www.onvif.org/type/video_encoder",
                "onvif://www.onvif.org/Profile/Streaming", f"onvif://www.onvif.org/name/{name}",
                "onvif://www.onvif.org/hardware/ptzsim", "onvif://www.onvif.org/location/simulator"]

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        try:
            root = ET.fromstring(data)
            # ElementTree drops prefix declarations, but Types holds prefixed QNames
            nsmap = {}
            for _, (prefix, uri) in ET.iterparse(io.BytesIO(data), events=("start-ns",)):
                nsmap.setdefault(prefix, uri)
        except ET.ParseError:
            return  # Core spec 7.3.6: silently discard broken packets
        message_id = text_of(root, "MessageID") or ""
        host = self.advertise_host or _local_ip_for(addr[0])
        probe = find(root, "Body", "Probe")
        resolve = find(root, "Body", "Resolve")
        if probe is not None and self._matches(probe, nsmap):
            self._send(addr, "ProbeMatches", "ProbeMatch", message_id, host)
            self.onvif.camera.record("ONVIF", f"WS-Discovery probe from {addr[0]}")
        elif resolve is not None and text_of(resolve, "EndpointReference", "Address") == self.address:
            self._send(addr, "ResolveMatches", "ResolveMatch", message_id, host)
            self.onvif.camera.record("ONVIF", f"WS-Discovery resolve from {addr[0]}")

    def _matches(self, probe: ET.Element, nsmap: Dict[str, str]) -> bool:
        types_elem = find(probe, "Types")
        for qname in (types_elem.text or "").split() if types_elem is not None else []:
            prefix, _, local = qname.rpartition(":")
            if (nsmap.get(prefix), local) not in DEVICE_TYPES:
                return False
        scopes_elem = find(probe, "Scopes")
        rule = scopes_elem.get("MatchBy", f"{WSD}/rfc3986") if scopes_elem is not None else ""
        wanted = (scopes_elem.text or "").split() if scopes_elem is not None else []
        if wanted and not rule.endswith(("/rfc3986", "/rfc2396", "/strcmp0")):
            return False  # unsupported matching rule: no answer (Core spec 7.3.6)
        if rule.endswith("/strcmp0"):
            return all(w in self.scopes for w in wanted)
        return all(any(scope_matches(w, d) for d in self.scopes) for w in wanted)

    def _envelope(self, action: str, body: str, relates_to: Optional[str] = None,
                  to: str = f"{WSA}/role/anonymous") -> bytes:
        self.message_number += 1
        relates = f"<a:RelatesTo>{escape(relates_to)}</a:RelatesTo>" if relates_to is not None else ""
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<s:Envelope xmlns:s="{NS["s"]}" xmlns:a="{WSA}" xmlns:d="{WSD}" '
            f'xmlns:dn="http://www.onvif.org/ver10/network/wsdl" xmlns:tds="{NS["tds"]}">'
            f"<s:Header><a:MessageID>uuid:{uuid.uuid4()}</a:MessageID>{relates}"
            f"<a:To>{to}</a:To><a:Action>{WSD}/{action}</a:Action>"
            f'<d:AppSequence InstanceId="{self.instance_id}" MessageNumber="{self.message_number}"/>'
            f"</s:Header><s:Body>{body}</s:Body></s:Envelope>").encode()

    def _endpoint(self, host: Optional[str], with_xaddrs: bool = True) -> str:
        xaddrs = f"<d:XAddrs>http://{host}:{self.http_port}/onvif/device_service</d:XAddrs>" if with_xaddrs else ""
        return (f"<a:EndpointReference><a:Address>{self.address}</a:Address></a:EndpointReference>"
                "<d:Types>dn:NetworkVideoTransmitter tds:Device</d:Types>"
                f"<d:Scopes>{' '.join(self.scopes)}</d:Scopes>{xaddrs}"
                "<d:MetadataVersion>1</d:MetadataVersion>")

    def _send(self, addr, action: str, item: str, relates_to: str, host: str) -> None:
        body = f"<d:{action}><d:{item}>{self._endpoint(host)}</d:{item}></d:{action}>"
        self.transport.sendto(self._envelope(action, body, relates_to), addr)

    def probe_match(self, relates_to: str, host: str) -> str:
        body = f"<d:ProbeMatches><d:ProbeMatch>{self._endpoint(host)}</d:ProbeMatch></d:ProbeMatches>"
        return self._envelope("ProbeMatches", body, relates_to).decode()

    def hello(self) -> None:
        """Multicast Hello when joining the network (Core spec 7.2)."""
        host = self.advertise_host or _local_ip_for(DISCOVERY_GROUP)
        body = f"<d:Hello>{self._endpoint(host)}</d:Hello>"
        self._multicast(self._envelope("Hello", body, to=WSD_TO))

    def bye(self) -> None:
        """Multicast Bye when leaving the network (Core spec 7.3.5)."""
        body = (f"<d:Bye><a:EndpointReference><a:Address>{self.address}</a:Address>"
                "</a:EndpointReference></d:Bye>")
        self._multicast(self._envelope("Bye", body, to=WSD_TO))

    def _multicast(self, data: bytes) -> None:
        if self.transport is not None and not self.transport.is_closing():
            try:
                self.transport.sendto(data, (DISCOVERY_GROUP, DISCOVERY_PORT))
            except OSError as err:
                log.debug("WS-Discovery multicast failed: %s", err)


async def serve_discovery(onvif: OnvifCamera, http_port: int, port: int = DISCOVERY_PORT,
                          advertise_host: Optional[str] = None, multicast: bool = True):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    sock.bind(("", port))
    if multicast:
        membership = struct.pack("4s4s", socket.inet_aton(DISCOVERY_GROUP), socket.inet_aton("0.0.0.0"))
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
        except OSError as err:
            log.warning("could not join WS-Discovery multicast group: %s", err)
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: DiscoveryProtocol(onvif, http_port, advertise_host), sock=sock)
    if multicast:
        protocol.hello()
    return transport
