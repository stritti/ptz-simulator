<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# ONVIF SOAP 1.2 examples

Namespaces used below:

```xml
<s>  = http://www.w3.org/2003/05/soap-envelope
<tt> = http://www.onvif.org/ver10/schema
<tds> = http://www.onvif.org/ver10/device/wsdl
<trt> = http://www.onvif.org/ver10/media/wsdl
<tptz> = http://www.onvif.org/ver20/ptz/wsdl
```

POST every envelope to the service path with
`Content-Type: application/soap+xml; charset=utf-8`.

## GetCapabilities (Device, PRE_AUTH)

```xml
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
  <s:Body>
    <tds:GetCapabilities>
      <tds:Category>All</tds:Category>
    </tds:GetCapabilities>
  </s:Body>
</s:Envelope>
```

Response contains `tds:GetCapabilitiesResponse/tds:Capabilities` with `tt:Device/tt:XAddr`,
`tt:Media/tt:XAddr`, `tt:PTZ/tt:XAddr` (e.g. `http://<host>:8080/onvif/device_service`).

## GetProfiles (Media)

```xml
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:trt="http://www.onvif.org/ver10/media/wsdl">
  <s:Body><trt:GetProfiles/></s:Body>
</s:Envelope>
```

Response: `trt:GetProfilesResponse/trt:Profiles` (token `Profile_1`) with
`tt:VideoSourceConfiguration`, `tt:VideoEncoderConfiguration`, `tt:PTZConfiguration`.

## GetStatus (PTZ)

```xml
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl">
  <s:Body>
    <tptz:GetStatus>
      <tptz:ProfileToken>Profile_1</tptz:ProfileToken>
    </tptz:GetStatus>
  </s:Body>
</s:Envelope>
```

Response `tptz:GetStatusResponse/tptz:PTZStatus` with
`<tt:Position><tt:PanTilt x="0.0" y="0.0" space="…/PanTiltSpaces/PositionGenericSpace"/><tt:Zoom x="0.0" space="…/ZoomSpaces/PositionGenericSpace"/></tt:Position>`
and `tt:MoveStatus`.

## ContinuousMove + Stop (PTZ)

```xml
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl"
            xmlns:tt="http://www.onvif.org/ver10/schema">
  <s:Body>
    <tptz:ContinuousMove>
      <tptz:ProfileToken>Profile_1</tptz:ProfileToken>
      <tptz:Velocity>
        <tt:PanTilt x="0.4" y="-0.2" space="http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace"/>
        <tt:Zoom x="0.0"/>
      </tptz:Velocity>
      <tptz:Timeout>PT1S</tptz:Timeout>
    </tptz:ContinuousMove>
  </s:Body>
</s:Envelope>
```

Velocity 0 on an axis stops that axis; an omitted axis keeps moving; `Timeout` ranges
PT0.1S…PT60S (default 5 s, each call extends it). Stop:

```xml
<tptz:Stop>
  <tptz:ProfileToken>Profile_1</tptz:ProfileToken>
  <tptz:PanTilt>true</tptz:PanTilt>
  <tptz:Zoom>true</tptz:Zoom>
</tptz:Stop>
```

## AbsoluteMove (PTZ)

```xml
<tptz:AbsoluteMove>
  <tptz:ProfileToken>Profile_1</tptz:ProfileToken>
  <tptz:Position>
    <tt:PanTilt x="0.5" y="0.0" space="http://www.onvif.org/ver10/tptz/PanTiltSpaces/PositionGenericSpace"/>
    <tt:Zoom x="0.5" space="http://www.onvif.org/ver10/tptz/ZoomSpaces/PositionGenericSpace"/>
  </tptz:Position>
</tptz:AbsoluteMove>
```

Out-of-range x/y/z (outside −1…1 / 0…1) must fault
`env:Sender / ter:InvalidArgVal / …`.

## Presets (PTZ)

```xml
<tptz:SetPreset>
  <tptz:ProfileToken>Profile_1</tptz:ProfileToken>
  <tptz:PresetName>gate</tptz:PresetName>
  <tptz:PresetToken>1</tptz:PresetToken>
</tptz:SetPreset>

<tptz:GetPresets>
  <tptz:ProfileToken>Profile_1</tptz:ProfileToken>
</tptz:GetPresets>

<tptz:GotoPreset>
  <tptz:ProfileToken>Profile_1</tptz:ProfileToken>
  <tptz:PresetToken>1</tptz:PresetToken>
  <!-- optional: <tptz:Speed><tt:PanTilt x="1" y="1" space="…/GenericSpeedSpace"/><tt:Zoom x="1"/></tptz:Speed> -->
</tptz:GotoPreset>

<tptz:RemovePreset>
  <tptz:ProfileToken>Profile_1</tptz:ProfileToken>
  <tptz:PresetToken>1</tptz:PresetToken>
</tptz:RemovePreset>
```

`SetPreset` while the camera moves → `env:Receiver / ter:Action / ter:MovingPTZ`.

## WS-Discovery Probe (UDP multicast 239.255.255.250:3702)

```xml
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
            xmlns:dn="http://www.onvif.org/ver10/network/wsdl"
            xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">
  <s:Header>
    <wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</wsa:Action>
    <wsa:MessageID>urn:uuid:…</wsa:MessageID>
    <wsa:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>
  </s:Header>
  <s:Body>
    <d:Probe>
      <d:Types>dn:NetworkVideoTransmitter</d:Types>
    </d:Probe>
  </s:Body>
</s:Envelope>
```

(WS-Discovery 5.2 requires the WS-Addressing headers Action/MessageID/To, using the
2004/08 addressing namespace `http://schemas.xmlsoap.org/ws/2004/08/addressing`.)

Answer: `d:ProbeMatches/d:ProbeMatch` with `d:XAddrs`, `d:Types dn:NetworkVideoTransmitter tds:Device`,
`d:Scopes` (incl. `onvif://www.onvif.org/name/<name>`), `d:MetadataVersion`, wrapped in
`d:ProbeMatches`.

## WS-Security UsernameToken header (PasswordDigest)

```xml
<s:Header>
  <Security xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
    <UsernameToken>
      <Username>admin</Username>
      <Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">…</Password>
      <Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">…</Nonce>
      <Created xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">2026-01-01T12:00:00.000Z</Created>
    </UsernameToken>
  </Security>
</s:Header>
```

Digest = `Base64(SHA1(raw_nonce + created + password))`.
