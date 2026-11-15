<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# ONVIF services and operations

Transport: HTTP/HTTPS, default port 80/443 (simulators often use 8080). SOAP 1.2, POST,
`Content-Type: application/soap+xml; charset=utf-8`. Default endpoint paths:

| Service | Path | WSDL namespace |
|---|---|---|
| Device | `/onvif/device_service` | `http://www.onvif.org/ver10/device/wsdl` (`tds:`) |
| Media | `/onvif/media_service` | `http://www.onvif.org/ver10/media/wsdl` (`trt:`) |
| PTZ | `/onvif/ptz_service` | `http://www.onvif.org/ver20/ptz/wsdl` (`tptz:`) |
| Imaging | `/onvif/imaging_service` | `http://www.onvif.org/ver20/imaging/wsdl` (`timg:`) |

Schema types: `tt:` = `http://www.onvif.org/ver10/schema`.

## Device service

- `GetCapabilities` (Category All/…), `GetServices` (with `IncludeCapability`),
  `GetSystemDateAndTime`, `GetDeviceInformation`, `GetWsdlUrl`, `GetEndpointReference`.
- Scopes: `GetScopes`, `SetScopes`, `AddScopes`, `RemoveScopes` — type/profile/hardware
  fixed, name and location configurable; WS-Discovery announces the current list in the
  scopes, e.g. `onvif://www.onvif.org/name/<name>`.
- `GetDiscoveryMode` / `SetDiscoveryMode` (`Discoverable` / `NonDiscoverable` —
  `NonDiscoverable` stops Hello and ProbeMatches).
- Network: `GetHostname`/`SetHostname`, `GetNetworkInterfaces`, `GetDNS`, `GetNTP`,
  `GetNetworkProtocols` (HTTP), `GetNetworkDefaultGateway`. The `Set…` variants and
  `SetSystemDateAndTime`, `SetSystemFactoryDefault`, `SystemReboot` are accepted but may
  change nothing on simple devices. User management (`CreateUsers`, `SetUser`,
  `DeleteUsers`) is commonly not implemented by PTZ-only devices.
- PRE_AUTH (no credentials needed, as on real cameras): `GetCapabilities`,
  `GetServices`, `GetServiceCapabilities`, `GetWsdlUrl`, `GetHostname`,
  `GetEndpointReference`, `GetSystemDateAndTime`.
- `GetCapabilities` must advertise the service XAddrs, at least Device, Media and PTZ:
  `<tt:Device><tt:XAddr>…/device_service</tt:XAddr></tt:Device>`,
  `<tt:Media><tt:XAddr>…/media_service</tt:XAddr>…`, `<tt:PTZ><tt:XAddr>…/ptz_service</tt:XAddr></tt:PTZ>`.
  Events/Media2 are typically absent from the capabilities.

## Media service

- One fixed profile (e.g. `Profile_1` token) with: video source configuration
  (`VideoSourceConfig_1`, e.g. 640×360), video encoder configuration (H.264,
  `VideoEncoderConfig_1`) and the PTZ configuration (with
  `DefaultContinuousPanTiltVelocitySpace` / `DefaultContinuousZoomVelocitySpace`).
- `GetProfiles`, `GetProfile`, `GetVideoSourceConfiguration(s)`,
  `Get(Compatible)VideoSourceConfiguration(s)`, `GetVideoSourceConfigurationOptions`,
  `SetVideoSourceConfiguration`, `Get(Compatible)VideoEncoderConfiguration(s)`,
  `GetVideoEncoderConfigurationOptions`, `SetVideoEncoderConfiguration` (store the
  values; out-of-range resolution/quality/framerate → fault `ter:ConfigModify`),
  `GetGuaranteedNumberOfVideoEncoderInstances`, `Add`/`Remove` `VideoSource` /
  `VideoEncoder` / `PTZ` `Configuration`.
- `GetStreamUri` returns the RTSP URI (e.g. `rtsp://<host>:554/stream`); without a
  source and encoder in the profile it fails with `ter:IncompleteConfiguration`.
  `GetSnapshotUri` is often not supported (`SnapshotUri="false"` in the profile).
- After `RemovePTZConfiguration`, PTZ moves/status/presets fail with `ter:NoPTZProfile`.

## PTZ service

- Nodes/configurations: `GetNodes`, `GetNode`, `GetConfigurations`, `GetConfiguration`,
  `GetConfigurationOptions`, `SetConfiguration`, `GetCompatibleConfigurations`.
  `GetNodes`/`GetConfiguration` must expose `SupportedPTZSpaces` (see the spaces
  reference) and `DefaultPTZSpeed`.
- Motion: `ContinuousMove` (Velocity with PanTilt x/y and Zoom; `Timeout`, default
  5 s, range PT0.1S…PT60S, every new call extends it), `Stop` (PanTilt/Zoom booleans),
  `AbsoluteMove` (Position + optional Speed), `RelativeMove` (Translation + optional
  Speed), `GetStatus` (Position PanTilt/Zoom + MoveStatus), `GotoHomePosition`,
  `SetHomePosition`.
- Presets: `GetPresets`, `SetPreset` (PresetName/PresetToken), `GotoPreset` (PresetToken,
  optional Speed), `RemovePreset`.
- Semantics: an omitted axis in `ContinuousMove` keeps moving; velocity 0 stops that
  axis. `SetPreset` while the camera moves fails with `ter:MovingPTZ`. Out-of-range
  velocity/position/timeout → `ter:InvalidArgVal`.

## Imaging service

Usually only white balance matters for PTZ integration: `GetImagingSettings`,
`SetImagingSettings`, `GetOptions` for the video source, mode AUTO/MANUAL, gains
0…255 (1.0 = neutral). Remote focus is supported (spec 5.3): `Move` with `Absolute`
(position 0…1), `Relative` (distance −1…1) or `Continuous` (speed −1…1) turns
autofocus off; `Stop` halts the lens; `GetStatus` returns the unitless position and
`IDLE`/`MOVING`; `GetMoveOptions` advertises all three kinds. Imaging `Move`/`Stop`
only touch the focus axis, never the PTZ unit.

## Not simulated by the ptzsim reference (common gaps)

Events, Media2, preset tours, auxiliary commands, HTTPS, user management, firmware.
These answer `ter:ActionNotSupported`.
