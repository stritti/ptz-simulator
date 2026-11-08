---
name: visca-interface
description: "Implement a VISCA-conformant PTZ camera interface (Sony VISCA over RS-232/RS-422 serial and VISCA over IP on UDP 52381): packet framing and terminator, the command and inquiry set, ACK/completion/error replies, the two command sockets, sequence numbers and value ranges. Use when building a VISCA client or a camera-side VISCA endpoint that must interoperate with real Sony/PTZOptics/Aver cameras and controllers; validate with scripts/visca_conformance.py."
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

# VISCA camera interface

Implement VISCA (Video System Control Architecture, Sony) exactly as the standard and the
target camera model define it. Two surfaces:

- **Serial** RS-232/RS-422, 9600 or 38400 baud 8N1, daisy chain of up to 7 cameras.
- **VISCA over IP**: raw VISCA payload in UDP datagrams on port **52381** with an 8-byte
  Sony header (payload type, length, 32-bit sequence number).

Reference documents:

- [references/visca-transports.md](references/visca-transports.md) — serial framing,
  VISCA-over-IP header, control commands, reply frames (ACK/completion/errors),
  command sockets, IF_Clear, address set, value ranges.
- [references/visca-commands.md](references/visca-commands.md) — the command set
  (power, zoom, focus, white balance, presets, pan/tilt drive, absolute/relative moves,
  home/reset, cancel) and the inquiry set with reply formats.

## Implementation rules

1. **Parse strictly, separate from I/O.** One function turns a raw packet into actions
   plus reply bytes; sockets/serial stay outside so handlers are unit-testable.
2. **Framing**: header `0x80 | address`, payload, terminator `0xFF`. Replies come from
   `(address + 8) << 4` — camera 1 answers `0x90`, camera 2 `0xA0` (over IP the address is
   fixed to 1, so replies are always `0x90`). Never answer a broadcast (`0x88 ...`) with
   an ACK.
3. **Replies**: commands → ACK `90 4z FF` then completion `90 5z FF` (z = socket 1/2);
   inquiries → `90 50 ... FF` immediately; errors → `90 60 02 FF` (syntax),
   `90 6z 41 FF` (not executable), `90 60 03 FF` (both sockets busy).
   Absolute moves/home/preset recalls complete only when the axes reach the target.
4. **Sockets**: a command takes the lowest free socket; a newer move takes over the axes
   of an older one; `8x 2z FF` cancels socket z (`90 6z 04 FF`, no completion) or answers
   `90 6z 05 FF`; `IF_Clear` (`8x 01 00 01 FF`) answers `90 50 FF`, stops all motion and
   empties both sockets.
5. **VISCA over IP**: echo the request's sequence number in every reply; payload type
   must match the packet kind (command `0x0100` vs inquiry `0x0110`), otherwise control
   reply `0x0201` + `0F 02`; a repeated sequence number is not executed again (control
   reply `0F 01`), except after an error reply; control command RESET (`0x0200`, payload
   `01`) is ACKed with `0x0201` + `01` and resets the sequence number.
6. **Value ranges** (classic Sony BRC/EVI/Axis command set): pan −2448…2448 (≈ ±170°),
   tilt −432…1296 (≈ −30…+90°), zoom 0x0000…0x4000 (1×…20×), focus 0x1000…0xF000,
   pan speed 1…0x18, tilt speed 1…0x17, presets 0…99 (hex 00…63), 14.4 units per degree.
   Clamp or reject out-of-range values the way the camera does.
7. **Model differences**: VISCA is not one standard — the command set differs per camera
   model (e.g. Sony ILME-FR7 uses white-balance code `04` = ATW). Check the target
   model's command list before relying on model-specific commands.

## Validate

Run the bundled smoke test against your camera-side endpoint (TCP raw, UDP raw or Sony
VISCA over IP):

```bash
python3 scripts/visca_conformance.py --host <camera-ip> --transport tcp --port 5678
python3 scripts/visca_conformance.py --host <camera-ip> --transport sony        # UDP 52381
```

To validate a *client*, point it at the reference simulator instead (skill
`ptz-conformance-testing`): `ptzsim serve --sony --tcp --udp` and connect the client to
52381 / 5678 / 1259. A client must treat the control replies `0F 01` / `0F 02` as a
failed request (no ACK or completion follows) and must use separate pan and tilt speed
maximums (max-speed inquiry `81 09 06 11 FF`; fallback pan `0x18`, tilt `0x17`); see the
checklist section "Client side".
