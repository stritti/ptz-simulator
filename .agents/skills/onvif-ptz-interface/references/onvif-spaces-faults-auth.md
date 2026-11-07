<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# ONVIF coordinate spaces, faults, discovery and authentication

## Coordinate spaces (generic spaces)

All PTZ vectors use normalised values and carry a `space` attribute URI.
Base: `http://www.onvif.org/ver10/tptz`.

| Vector | Space URI | Range |
|---|---|---|
| Pan/tilt position | `…/PanTiltSpaces/PositionGenericSpace` | x, y ∈ −1…1 (≈ ±170° pan; tilt −1 = −30°, 0 = level, +1 = +90°) |
| Pan/tilt translation | `…/PanTiltSpaces/TranslationGenericSpace` | x, y ∈ −1…1 (RelativeMove delta) |
| Pan/tilt velocity | `…/PanTiltSpaces/VelocityGenericSpace` | x, y ∈ −1…1 |
| Pan/tilt speed | `…/PanTiltSpaces/GenericSpeedSpace` | x, y ∈ 0…1 |
| Zoom position | `…/ZoomSpaces/PositionGenericSpace` | 0…1 (1×…20×) |
| Zoom translation | `…/ZoomSpaces/TranslationGenericSpace` | −1…1 |
| Zoom velocity | `…/ZoomSpaces/VelocityGenericSpace` | −1…1 |
| Zoom speed | `…/ZoomSpaces/ZoomGenericSpeedSpace` | 0…1 |

Declare them in the PTZ node (`tt:SupportedPTZSpaces`) and set `tt:DefaultPTZSpeed`.
Convert the camera's native units at the edge (e.g. VISCA pan ±2448 ≈ ±170° ↔ −1…1).

## SOAP 1.2 faults

Envelope namespace `s` = `http://www.w3.org/2003/05/soap-envelope`; ONVIF fault subcodes
are QNames in the ONVIF **error namespace** `http://www.onvif.org/ver10/error` (the
reference binds it to the prefix `ter`; the prefix itself is arbitrary — resolve QNames
by namespace URI, not prefix). Structure:

```xml
<s:Fault>
  <s:Code><s:Value>s:Sender</s:Value>
    <s:Subcode><s:Value>ter:InvalidArgVal</s:Value>
      <s:Subcode><s:Value>ter:NoProfile</s:Value></s:Subcode>
    </s:Subcode>
  </s:Code>
  <s:Reason><s:Text xml:lang="en">unknown profile</s:Text></s:Reason>
</s:Fault>
```

Rules: `env:Sender` faults (client error) are sent with HTTP 400, `env:Receiver` with
HTTP 500 in this reference implementation; real cameras commonly use 500 for both —
clients must parse the SOAP fault, not only the status code. Common chains:

- unknown profile: `env:Sender / ter:InvalidArgVal / ter:NoProfile`
- no PTZ configuration: `ter:NoPTZProfile`
- out-of-range value: `ter:InvalidArgVal` (+ leaf, e.g. `ter:NoProfile`)
- timeout outside PT0.1S…PT60S: `ter:InvalidArgVal / ter:TimeoutNotSupported`
- SetPreset while moving: `env:Receiver / ter:Action / ter:MovingPTZ`
- unsupported operation: `env:Receiver / ter:ActionNotSupported` (optionally
  `…/ter:OptionalActionNotSupported`)
- bad configuration values: `env:Sender / ter:InvalidArgVal / ter:ConfigModify`

Non-GET/POST HTTP methods → 405. Empty SOAP body → 400 + `ter:InvalidArgVal`.

## WS-Discovery (UDP 3702, multicast 239.255.255.250)

- Types: `dn:NetworkVideoTransmitter tds:Device`
  (`dn` = `http://www.onvif.org/ver10/network/wsdl`, `d` = `http://schemas.xmlsoap.org/ws/2005/04/discovery`).
- Camera sends **Hello** on start and **Bye** on exit (with `AppSequence`).
- Client sends **Probe** (`d:Types`, optional `d:Scopes` matching rfc3986/strcmp0);
  camera answers **ProbeMatches** with `d:XAddrs` (e.g.
  `http://<ip>:8080/onvif/device_service`), `d:Types`, `d:Scopes`, `d:MetadataVersion`.
- `Resolve`/`ResolveMatches` for direct probing. `SetDiscoveryMode(NonDiscoverable)`
  stops Hello and ProbeMatches.

## Authentication

Two mechanisms, either or both (configurable):

1. **HTTP digest** (RFC 2617): answer unauthenticated requests with HTTP 401 and a
   `WWW-Authenticate: Digest …` challenge (realm, nonce, qop="auth"); also wrong
   credentials get 401 with a new challenge (Core spec figure 4). The response digest is
   `MD5(HA1:nonce:nc:cnonce:qop:HA2)` with `HA1 = MD5(user:realm:password)`,
   `HA2 = MD5(method:uri)`.
2. **WS-Security UsernameToken** in the SOAP header
   (`http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd`):
   - `PasswordDigest`: `Base64(SHA1(nonce_raw + created_utf8 + password))`, nonce sent
     Base64-encoded with `EncodingType="…#Base64Binary"`, `Created` UTC ISO-8601
     (`2026-01-01T12:00:00.000Z`), namespace
     `http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd`.
   - `PasswordText` (Type `…#PasswordText`) may also be accepted.

PRE_AUTH operations (no credentials, like real cameras): `GetSystemDateAndTime`,
`GetCapabilities`, `GetServices`, `GetServiceCapabilities`, `GetWsdlUrl`,
`GetHostname`, `GetEndpointReference`.
