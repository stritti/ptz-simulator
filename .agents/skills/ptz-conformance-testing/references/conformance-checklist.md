<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# Conformance checklist

What "reference-conformant" means per protocol, checked against the ptzsim reference.
The protocol sections check the **camera side**; [Client side](#client-side) lists the
pitfalls of a client that drives a camera. Those show up only end to end: run the
client against ptzsim and assert on the camera model with the `ptzsim.testing`
helpers (see `ptzsim-usage.md`).

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
      `FF <addr> 00 <request checksum>` (alarm byte 0x00); wrong checksum or
      contradicting direction bits → no reply; frames for other addresses → silently
      ignored.
- [ ] Drive bitmask in cmd2: 0x02 pan right, 0x04 pan left, 0x08 tilt up, 0x10 tilt
      down, 0x20 zoom tele, 0x40 zoom wide, 0x80 focus far; cmd1 bit 0 = focus near.
      A drive frame sets the whole motion state (cleared bit = axis stops).
- [ ] Extended commands (cmd2 bit 0 set): 0x03 set / 0x05 clear / 0x07 call preset,
      preset number in data2 (0–99); call of an unset preset → no response.
- [ ] Stop all: `FF <addr> 00 00 00 00 <chk>`. Speeds 0x00–0x3F (0x00 = slowest, not
      stop) and 0x40 pan turbo; zoom/focus speed via `00 25` / `00 27` (0x00–0x03); drive
      commands stop after 15 s without a new drive command.
- [ ] Parser resyncs on 0xFF and discards bad-checksum candidates byte by byte.
- [ ] Position: set `00 4B/4D/4F` (general response), query `00 51/53/55` → Extended
      Response `FF a 00 59/5B/5D msb lsb cksm`; pan/tilt in 1/100° 0–35999 (tilt 0 =
      horizon, 9000 = down), zoom = magnification / limit × 65535.

## Client side

Checks for code that **drives** a camera. Run the client against ptzsim and check the
camera model after each step (`assert_stopped`, `assert_no_errors` from
`ptzsim.testing`); a hung or slow call usually means the client missed a reply.

### VISCA

- [ ] VISCA over IP control replies: a message the camera rejects with control reply
      `0x0201` + `0F 01` (abnormality in the sequence number, e.g. a repeated number)
      or `0F 02` (abnormality in the message type) gets **no ACK and no completion**.
      Treat the control reply as the answer: fail the pending request at once instead
      of waiting for the timeout (a client that ignores it waits its full timeout, e.g.
      15 s on a preset recall). Then resynchronise: send RESET (`0x0200`, payload `01`,
      answer `0x0201` + `01`) and restart the counter, or retransmit with a new sequence
      number if the result is still needed (after `0F 01` on a retransmission the
      command was already performed).
- [ ] Sequence numbers: increment per message, wrap to 0; send RESET when the client
      (re)connects, since the camera remembers the last number per sender.
- [ ] Speed ranges: pan and tilt speeds have **separate** maximums. Ask the camera with
      the max-speed inquiry `81 09 06 11 FF` → `90 50 ww zz FF` (ww pan, zz tilt
      maximum) and scale to that. Until it has answered, use the conservative classic
      maximums pan `0x18`, tilt `0x17` (Sony BRC/EVI, Axis; ptzsim answers `18 17`).
      A client that uses `0x18` for both gets `90 60 02 FF` (syntax error) on a
      full-speed tilt. Some models allow more (the ILME-FR7 list gives 18 normal / 32
      extended for both axes), which is why the inquiry wins over any fallback.
- [ ] Every command waits for its ACK (`90 4z FF`) and then the completion
      (`90 5z FF`) **or** an error (`90 6z …`); `90 6z 41 FF` (e.g. recall of an empty
      preset) and `90 60 02 FF` end the request as failed.
- [ ] Inquiries are answered with `90 50 … FF` without a socket and without an ACK.
- [ ] After Stop (`8x 01 06 01 vv ww 03 03 FF`) or a drive with an axis set to stop,
      no axis keeps moving.

### ONVIF

- [ ] `ContinuousMove`: an **omitted** axis keeps its current movement (PTZ Service
      Specification, ContinuousMove: "If the pan/tilt element is omitted, the current
      pan/tilt movement shall not be affected … The same holds for the zoom element");
      only velocity 0 stops an axis. Send PanTilt in every ContinuousMove, and Zoom too
      when the PTZ node has a continuous zoom velocity space, with 0 for the axes that
      should stand still. A client that drops Zoom when its zoom speed is 0 keeps the
      zoom running after switching to pan.
- [ ] `Stop` with `PanTilt` and `Zoom` both `true` (or both omitted) after every
      jog; check that the camera reports `MoveStatus` IDLE afterwards.
- [ ] `Timeout` within PT0.1S…PT60S (outside → `ter:TimeoutNotSupported`); a client
      that jogs for longer repeats ContinuousMove before the timeout ends the move.
- [ ] Parse the SOAP fault (subcode chain), not only the HTTP status; retry a 401 with
      the digest challenge, and do not retry with the same wrong credentials.
- [ ] Preset tokens are opaque strings (ptzsim uses decimal numbers): pass them back
      unchanged, do not parse them.

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
