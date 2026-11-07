---
name: pelco-d-interface
description: "Implement a Pelco-D-conformant PTZ camera interface (serial RS-485/RS-422, 2400-38400 baud 8N1): 7-byte frames FF addr cmd1 cmd2 data1 data2 checksum, the 4-byte general response, the command-2 motion bitmask, extended preset opcodes, speed fields 0x00..0x3F plus 0xFF turbo, addressing 1..255 and checksum/sync error behaviour. Use when building a Pelco-D client or camera-side endpoint for surveillance cameras; validate with scripts/pelco_conformance.py against the endpoint's serial port."
license: MIT
compatibility: The bundled conformance script needs only Python 3.8+ (standard library) and a serial device path (e.g. a pty). The reference simulator ptzsim >= 0.4.0 (https://github.com/stritti/ptz-simulator) speaks Pelco-D via --pelco-d.
metadata:
  author: stritti
  version: "1.0.0"
  source: https://github.com/stritti/ptz-simulator
---

<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# Pelco-D camera interface

Pelco-D is the open serial PTZ protocol used by most surveillance cameras over
RS-485/RS-422 (2400 baud default, 8N1, up to 255 addresses on one bus). The reference
simulator ptzsim implements it since 0.4.0 (`--pelco-d [LINK]`, `--pelco-d-address`).

Reference: [references/pelco-d-frames.md](references/pelco-d-frames.md) — frame layout,
checksum, response frame, command bitmasks, extended commands, speeds, resync rules.

## Implementation rules

1. **Frame**: 7 bytes `FF <addr> <cmd1> <cmd2> <data1> <data2> <checksum>` with
   `checksum = (addr + cmd1 + cmd2 + data1 + data2) mod 256`.
2. **Response**: every executed command is answered with the 4-byte general response
   `FF <addr> <cmd1 echo> <request checksum>`. A frame with a wrong checksum gets
   **no reply**; frames for other addresses are ignored silently (shared RS-485 bus).
3. **Motion (drive)**: cmd2 is a bitmask — 0x02 pan right, 0x04 pan left, 0x08 tilt up,
   0x10 tilt down, 0x20 zoom tele, 0x40 zoom wide, 0x80 focus far; cmd1 bit 0 = focus
   near. A drive frame describes the **whole motion state**: an axis whose bit is
   cleared stops. data1 = pan speed, data2 = tilt speed (0x00–0x3F, 0xFF = turbo);
   for zoom commands data1 is the zoom speed.
4. **Extended commands** (cmd2 bit 0 set): 0x03 set preset, 0x05 clear preset,
   0x07 call preset, preset number in data2 (0–99). Stop all = `FF a 00 00 00 00 chk`.
5. **Focus** commands only move in manual focus mode (ignored while autofocus is on).
6. **Presets**: the same 100 presets as VISCA/ONVIF. Calling an unset preset gets no
   response. Pelco-D has **no position inquiry** — read position via VISCA/ONVIF on
   the same camera (e.g. `ptzsim serve --sony --pelco-d`).
7. **Parsing**: resync on the sync byte 0xFF — drop garbage before it, and discard a
   7-byte candidate with a wrong checksum byte by byte so a stray 0xFF cannot swallow
   a following valid frame.

## Validate

Against your camera-side endpoint, point the bundled smoke test at its serial device:

```bash
python3 scripts/pelco_conformance.py --port /dev/ttyUSB0 --address 1
```

To validate a *client*, run the reference simulator and open its pty in the client
(skill `ptz-conformance-testing`): `ptzsim serve --pelco-d /tmp/ttyPelcoD`.
