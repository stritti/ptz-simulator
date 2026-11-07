---
name: onvif-ptz-interface
description: "Implement an ONVIF Profile S/T conformant PTZ service (SOAP 1.2 over HTTP): Device, Media and PTZ services with their operations, WS-Discovery on UDP 3702, HTTP digest and WS-Security UsernameToken (PasswordDigest) authentication, generic pan/tilt/zoom coordinate spaces (-1..1 / 0..1), spec fault chains (env:Sender/ter:InvalidArgVal/...) and timeout semantics. Use when building a camera-side ONVIF endpoint or an ONVIF client that must work with VMS like Milestone or Genetec; validate with scripts/onvif_conformance.py against the ptzsim reference."
license: MIT
compatibility: The bundled conformance script needs only Python 3.8+ (standard library). The reference simulator ptzsim (https://github.com/stritti/ptz-simulator) runs on Python 3.8+ with no dependencies.
metadata:
  author: stritti
  version: "1.0.0"
  source: https://github.com/stritti/ptz-simulator
---

<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# ONVIF PTZ interface (Profile S / T)

Implement the ONVIF PTZ service the way the ONVIF Core and PTZ Service specifications
define it, so VMS and ONVIF clients (onvif-zeep, …) can discover and drive the camera.

Reference documents:

- [references/onvif-services.md](references/onvif-services.md) — the three services and
  their operations (Device, Media, PTZ, Imaging), which operations work without
  authentication, endpoint paths and ports.
- [references/onvif-spaces-faults-auth.md](references/onvif-spaces-faults-auth.md) —
  coordinate spaces and their URIs, value ranges, SOAP 1.2 fault chains and HTTP status
  codes, WS-Discovery (Hello/Probe/ProbeMatches/Bye), WS-Security UsernameToken and
  HTTP digest auth.
- [references/soap-examples.md](references/soap-examples.md) — ready-to-send SOAP 1.2
  envelopes for the core operations (GetCapabilities, GetProfiles, GetStatus,
  ContinuousMove, Stop, AbsoluteMove, presets) and a fault example.

## Implementation rules

1. **SOAP 1.2** (`http://www.w3.org/2003/05/soap-envelope`), POST with
   `Content-Type: application/soap+xml; charset=utf-8`. Unknown operations → SOAP fault
   `env:Receiver / ter:ActionNotSupported` (HTTP 500). Non-GET/POST methods → 405.
2. **Discovery**: answer WS-Discovery probes on UDP 3702 (multicast 239.255.255.250),
   types `dn:NetworkVideoTransmitter tds:Device`; send Hello on start, Bye on shutdown;
   ProbeMatches carries the XAddrs, e.g. `http://<ip>:<port>/onvif/device_service`.
3. **Authentication** (when configured): HTTP digest (RFC 2617, answer 401 with a
   `WWW-Authenticate` challenge, also for wrong credentials) and/or WS-Security
   UsernameToken with `PasswordDigest` = Base64(SHA-1(nonce + created + password)),
   nonce Base64-encoded, `Created` in UTC ISO-8601. `PasswordText` may also be accepted.
   These operations stay open without credentials (PRE_AUTH): `GetSystemDateAndTime`,
   `GetCapabilities`, `GetServices`, `GetServiceCapabilities`, `GetWsdlUrl`,
   `GetHostname`, `GetEndpointReference`.
4. **Coordinates** use the generic ONVIF spaces: pan −1…1 (≈ ±170°), tilt −1…1
   (−1 = −30°, 0 = level, +1 = +90°), zoom 0…1 (1×…20×), velocities −1…1. Declare the
   spaces in the PTZ node's `SupportedPTZSpaces` and use the `space` attribute URIs.
5. **Faults** use the spec chains, e.g. unknown profile → HTTP 400 + fault
   `env:Sender / ter:InvalidArgVal / ter:NoProfile`; out-of-range velocity, position,
   translation or speed → `ter:InvalidArgVal / ter:InvalidVelocity|InvalidPosition|
   InvalidTranslation|InvalidSpeed`; timeout outside PT0.1S…PT60S →
   `ter:TimeoutNotSupported`; an unsupported `space` URI → `ter:SpaceNotSupported`;
   `SetPreset` with an unknown `PresetToken` → `ter:NoToken`, while moving →
   `env:Receiver / ter:Action / ter:MovingPTZ` (PTZ spec 25.12, chapter 5); after
   `RemovePTZConfiguration` PTZ operations fail with `ter:NoPTZProfile`.
6. **Motion semantics**: `ContinuousMove` velocity 0 on an axis stops that axis; an
   omitted axis keeps moving; `Timeout` (default 5 s, PT0.1S…PT60S) ends the move and
   every new call extends it. `Stop` halts pan/tilt and zoom. `AbsoluteMove` takes
   `Position` (position-space URIs), `RelativeMove` takes `Translation`
   (translation-space URIs); both accept an optional `Speed`; out-of-range values fault.
7. **Media profile**: one profile (e.g. `Profile_1`) with a video source configuration
   (e.g. 640×360), an encoder configuration and a PTZ configuration token. `GetProfiles`
   must return it with the PTZ configuration; `GetStreamUri` returns the RTSP URI.
8. **Presets**: `SetPreset`/`GotoPreset`/`RemovePreset`/`GetPresets` with `PresetToken`;
   `GotoPreset` may carry a `Speed` that overrides the preset speed. The reference
   simulator parses tokens as **decimal** (`int(token)` in `OnvifCamera._preset_number`)
   and emits decimal tokens in `GetPresets` (`token="5"`), so use `0`…`99`; the hex
   `00`…`63` form is the VISCA command byte, not the ONVIF token — match the target
   camera's convention.

## Validate

```bash
python3 scripts/onvif_conformance.py --host <camera-ip> --port 8080
python3 scripts/onvif_conformance.py --host 127.0.0.1 --user admin --password secret --discovery
```

To validate a *client*, point it at the reference simulator (skill
`ptz-conformance-testing`): `ptzsim serve --onvif --onvif-user admin --onvif-password secret`
and let the client discover or enter `http://<ip>:8080/onvif/device_service`.
