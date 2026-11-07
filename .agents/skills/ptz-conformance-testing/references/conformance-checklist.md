<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# Conformance checklist

What "reference-conformant" means per protocol, checked against the ptzsim reference.

## VISCA (any transport)

- [ ] Packet framing: header `0x8x`, terminator `0xFF`; broadcast `0x88 …` never ACKed.
- [ ] Inquiries (`8x 09 … FF`) answer immediately with `90 50 … FF` (no socket).
- [ ] Commands ACK `90 4z FF` then complete `90 5z FF` (z = socket 1/2, same socket);
      absolute moves/home/preset recalls complete only when the axes reached the target.
- [ ] Errors: syntax `90 60 02 FF`; buffer full `90 60 03 FF`; not executable
      `90 6z 41 FF`; cancel `8x 2z FF` → `90 6z 04 FF` (no completion) or `90 6z 05 FF`;
      IF_Clear `8x 01 00 01 FF` → `90 50 FF`, stops motion, empties both sockets.
- [ ] Two sockets: lowest free socket first; newer move takes over axes of an older one.
- [ ] Address set `88 30 0w FF` → `88 30 0(w+1) FF`.
- [ ] VISCA over IP (UDP 52381): 8-byte header `>HHI`, types 0x0100/0x0110/0x0111/
      0x0120/0x0200/0x0201; replies echo the request sequence number; repeated sequence
      not re-executed (`0F 01`), wrong type (`0F 02`); RESET control command ACKed
      (`0x0201` + `01`); after a VISCA error the same sequence is executed again;
      any address accepted, replies from `0x90`.
- [ ] Value ranges: pan ±2448, tilt −432…1296, zoom 0x0000…0x4000, focus 0x1000…0xF000,
      pan speed 1…0x18, tilt speed 1…0x17 (00 = same as pan), presets hex 00…63.

## ONVIF (Profile S/T)

- [ ] SOAP 1.2 envelopes; POST `application/soap+xml`; unknown operation → fault
      `env:Receiver/ter:ActionNotSupported` (HTTP 500); non-GET/POST → 405.
- [ ] WS-Discovery: Hello on start, Bye on exit, Probe → ProbeMatches with XAddrs and
      scopes (`onvif://www.onvif.org/name/<name>`), types `dn:NetworkVideoTransmitter
      tds:Device`; `NonDiscoverable` stops Hello/ProbeMatches.
- [ ] PRE_AUTH operations without credentials: GetSystemDateAndTime, GetCapabilities,
      GetServices, GetServiceCapabilities, GetWsdlUrl, GetHostname, GetEndpointReference.
- [ ] Auth: HTTP digest 401 + challenge (also for wrong credentials) and/or WSSE
      UsernameToken PasswordDigest (Base64(SHA1(nonce+created+password))).
- [ ] GetCapabilities advertises Device/Media/PTZ XAddrs; GetServices lists the PTZ
      namespace; GetProfiles returns the profile with source/encoder/PTZ configuration.
- [ ] Coordinates in the generic spaces (pan/tilt −1…1, zoom 0…1, velocities −1…1) with
      `space` URIs declared in SupportedPTZSpaces; out-of-range values fault
      `env:Sender/ter:InvalidArgVal/…`.
- [ ] Fault chains: unknown profile → `…/ter:NoProfile`; no PTZ configuration →
      `ter:NoPTZProfile`; timeout outside PT0.1S…PT60S → `ter:TimeoutNotSupported`;
      SetPreset while moving → `env:Receiver/ter:Action/ter:MovingPTZ`.
- [ ] Motion: ContinuousMove velocity 0 stops that axis, omitted axis keeps moving,
      Timeout default 5 s extended by every call; Stop halts; AbsoluteMove/RelativeMove
      clamp or fault; GetStatus returns Position + MoveStatus.
- [ ] Presets: Set/Get/Goto/Remove with PresetToken; GotoPreset Speed overrides.

## Pelco-D (serial RS-485, ptzsim >= 0.4.0)

- [ ] Frame: 7 bytes `FF <addr> <cmd1> <cmd2> <data1> <data2> <checksum>`,
      `checksum = (addr + cmd1 + cmd2 + data1 + data2) mod 256`.
- [ ] Every executed command answers the 4-byte general response
      `FF <addr> <cmd1 echo> <request checksum>`; wrong checksum → no reply; frames for
      other addresses → silently ignored.
- [ ] Drive bitmask in cmd2: 0x02 pan right, 0x04 pan left, 0x08 tilt up, 0x10 tilt
      down, 0x20 zoom tele, 0x40 zoom wide, 0x80 focus far; cmd1 bit 0 = focus near.
      A drive frame sets the whole motion state (cleared bit = axis stops).
- [ ] Extended commands (cmd2 bit 0 set): 0x03 set / 0x05 clear / 0x07 call preset,
      preset number in data2 (0–99); call of an unset preset → no response.
- [ ] Stop all: `FF <addr> 00 00 00 00 <chk>`. Speeds 0x00–0x3F (0x00 = slowest, not
      stop) and 0xFF turbo; data1 doubles as zoom speed for zoom commands.
- [ ] Parser resyncs on 0xFF and discards bad-checksum candidates byte by byte.
- [ ] No position inquiry in Pelco-D — position is read via VISCA/ONVIF instead.

## Known deliberate deviations of the ptzsim reference

- ONVIF: checked against the ONVIF Core Specification; PTZ fault subcodes are **not**
  verified against the PTZ Service Specification; responses are not XSD-validated
  automatically. Not simulated: Events, Media2, user management, firmware, HTTPS,
  imaging beyond white balance, preset tours.
- VISCA: follows the classic 4-digit Sony BRC/EVI/Axis command set — check the target
  model's command list for model-specific codes (e.g. FR7 white balance `04` = ATW,
  5-digit positions).
- Not simulated at all: Pelco-P, Panasonic AW CGI, PTZOptics HTTP-CGI,
  Sony CGI, Axis VAPIX, Canon XC.
