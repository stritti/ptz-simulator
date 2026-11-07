---
title: ONVIF
---

<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# ONVIF

References: ONVIF **Core** Specification 26.06, **Media** Service Specification 24.12,
**PTZ** Service Specification 25.12 and **Imaging** Service Specification 18.12. ONVIF
lets these documents be redistributed unchanged, so copies are included here:

| Document | Copy | Official source |
|---|---|---|
| Core 26.06 | [PDF](/specs/onvif/ONVIF-Core-Spec-v2606.pdf) | [onvif.org](https://www.onvif.org/specs/2606/ONVIF-Core-Spec-v2606.pdf) |
| Media 24.12 | [PDF](/specs/onvif/ONVIF-Media-Service-Spec-v2412.pdf) | [onvif.org](https://www.onvif.org/profiles/specifications/) |
| PTZ Service 25.12 | [PDF](/specs/onvif/ONVIF-PTZ-Service-Spec-v2512.pdf) | [onvif.org](https://www.onvif.org/specs/2512/ONVIF-PTZ-Service-Spec-v2512.pdf) |
| Imaging 18.12 | [PDF](/specs/onvif/ONVIF-Imaging-Service-Spec-v1812.pdf) | [onvif.org](https://www.onvif.org/specs/srv/img/ONVIF-Imaging-Service-Spec-v1812.pdf) |

The copies are © ONVIF™ and come with ONVIF's copyright notice, licence and
disclaimer, which are on page 2 of each PDF. They are not modified. The MIT licence
of ptzsim does not cover them.

ptzsim module: `ptzsim/onvif.py`, option `--onvif [PORT]` (SOAP 1.2 over HTTP,
default port 8080).

## Core: transport, errors, security

| Section | Requirement | ptzsim |
|---|---|---|
| Core 5.8.2 | SOAP 1.2 faults with the subcode chains `ter:…` | yes; `env:Sender` faults use HTTP 400 and `env:Receiver` faults use HTTP 500 |
| Core 5.8.2.4 | HTTP errors | methods other than GET/POST get 405 |
| Core 5.9.1 | HTTP digest authentication (RFC 2617), 401 with a challenge | yes (`--onvif-user`, `--onvif-auth digest`) |
| Core 5.9.5 | WS-Security UsernameToken, PasswordDigest and PasswordText | yes (`--onvif-auth wsse`) |
| Core 5.9.4.4 | some calls work before authentication | GetSystemDateAndTime, GetCapabilities, GetServices, GetServiceCapabilities, GetWsdlUrl, GetHostname, GetEndpointReference |
| Core 5.9.3 | SHA-256 digest | *missing* (MD5 only) |
| — | HTTPS | *missing* (issue #33) |

## Core: discovery (chapter 7)

| Section | Requirement | ptzsim |
|---|---|---|
| Core 7.3.1 | stable endpoint reference (`urn:uuid:`) | yes, derived from the camera name |
| Core 7.3.2 | Hello on start, with types, scopes and XAddrs | yes, Types `dn:NetworkVideoTransmitter tds:Device`, AppSequence |
| Core 7.3.3 | Probe/ProbeMatch, matched by type and scope (rfc3986, strcmp0) | yes |
| Core 7.3.4 | Resolve/ResolveMatch | yes |
| Core 7.3.5 | Bye when leaving | yes, on exit |
| Core 7.2, 8.3.18–19 | discovery mode discoverable/non-discoverable | yes, GetDiscoveryMode/SetDiscoveryMode |

## Core: device management (chapter 8)

| Section | Operation | ptzsim |
|---|---|---|
| 8.1.1 | GetWsdlUrl | yes |
| 8.1.2.2–8.1.2.4 | GetServices, GetServiceCapabilities, GetCapabilities | yes (device, media, PTZ, imaging) |
| 8.2.1–8.2.2 | GetHostname, SetHostname | yes |
| 8.2.4–8.2.15 | GetDNS, GetNTP, GetNetworkInterfaces, GetNetworkProtocols, GetNetworkDefaultGateway and their Set operations | Get answers with the current values; Set is accepted but *not simulated* |
| 8.3.1 | GetDeviceInformation | yes |
| 8.3.6–8.3.8 | Get/SetSystemDateAndTime, SetSystemFactoryDefault | Get yes; Set accepted, *not simulated* |
| 8.3.13 | SystemReboot | accepted, *not simulated* |
| 8.3.14–8.3.17 | GetScopes, SetScopes, AddScopes, RemoveScopes | yes; fixed scopes cannot be removed (`ter:OperationProhibited/ter:FixedScope`) |
| 8.4.3 | GetUsers | yes; Create/Delete/SetUser *missing* |
| — | Events service | *missing* (issue #30) |

## Media service

| Section | Operation | ptzsim |
|---|---|---|
| 5.2.2–5.2.3 | GetProfiles, GetProfile | one profile `Profile_1` with video source, encoder and PTZ configuration |
| 5.2.5, 5.2.8, 5.2.14, 5.2.17 | Add/Remove video source, video encoder and PTZ configuration | yes; without the PTZ configuration, PTZ calls fail with `ter:NoPTZProfile` |
| 5.3.1 | GetVideoSources | `VideoSource_1`, 640×360, 25 fps |
| 5.4.1–5.4.5 | video source configuration operations | yes |
| 5.5.1–5.5.6 | video encoder configuration operations, GetGuaranteedNumberOfVideoEncoderInstances | yes (H.264) |
| 5.15.1 | GetStreamUri | returns `--rtsp-uri`; ptzsim does not stream (issue #35) |
| 5.16.1 | GetSnapshotUri | *missing*, `SnapshotUri="false"` |
| 5.21 | GetServiceCapabilities | yes |

## PTZ service

| Section | Operation / requirement | ptzsim |
|---|---|---|
| 5.1 | GetNodes, GetNode (`ter:NoEntity`) | node `PTZNode_1` with the generic spaces, 100 presets, home support |
| 5.2 | GetConfigurations, GetConfiguration, GetConfigurationOptions, SetConfiguration, GetCompatibleConfigurations | yes; SetConfiguration accepts the known token but changes nothing |
| 5.3 | all move commands are non-blocking | yes |
| 5.3.1 | AbsoluteMove: `ter:InvalidPosition`, `ter:SpaceNotSupported`, `ter:InvalidSpeed`; an omitted axis keeps its motion | yes; `--onvif-no-absolute` simulates a node without absolute spaces |
| 5.3.2 | RelativeMove: `ter:InvalidTranslation`; a target past the end stops is clipped at the border | yes |
| 5.3.3 | ContinuousMove: Timeout overrides DefaultPTZTimeout (PT5S), `ter:TimeoutNotSupported` outside PT0.1S–PT60S, `ter:InvalidVelocity`; velocity 0 stops an axis, an omitted axis keeps moving | yes |
| 5.3.5 | Stop with PanTilt/Zoom flags, both default to true | yes |
| 5.3.7 | GetStatus: position in the default spaces, MoveStatus IDLE/MOVING, UtcTime | yes |
| 5.4.1 | SetPreset: new preset without a token, update with an existing token (`ter:NoToken` otherwise), `ter:MovingPTZ`, `ter:TooManyPresets` | yes |
| 5.4.2–5.4.4 | GetPresets, GotoPreset (Speed, `ter:NoToken`), RemovePreset | yes |
| 5.5.1–5.5.2 | GotoHomePosition (with Speed), SetHomePosition | yes; the home position can be overwritten (`FixedHomePosition="false"`) |
| 5.6 | auxiliary commands | *missing* |
| 5.8 | preset tours | *missing* |
| 5.3.4, 5.3.6 | GeoMove, MoveAndStartTracking | *missing* (optional) |
| 5.7 | generic spaces: position, translation, velocity −1…1 (zoom position 0…1), speed 0…1 | yes; no other spaces are offered |

## Imaging service

| Section | Operation | ptzsim |
|---|---|---|
| 5.1.2–5.1.4 | GetImagingSettings, SetImagingSettings, GetOptions | white balance only: mode AUTO/MANUAL, Cr/Cb gains 0…255 (128 = VISCA `0x80`) |
| 5.3.1–5.3.4 | Move, GetMoveOptions, Stop, GetImagingStatus | GetMoveOptions and GetStatus answer empty, Move/Stop give `ter:ActionNotSupported` (focus via ONVIF: issue #34) |
| 5.2 | imaging presets | *missing* |
