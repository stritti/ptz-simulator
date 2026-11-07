<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# Pelco-D frame reference

Serial RS-485/RS-422, 2400 baud (default; up to 38400), 8 data bits, no parity, 1 stop
bit (8N1). Up to 255 camera addresses on one bus; frames for other addresses are
ignored silently.

## Frame layout (7 bytes)

```
+------+-------+------+------+-------+-------+----------+
| 0xFF | addr  | cmd1 | cmd2 | data1 | data2 | checksum |
| sync | 1-255 |      |      |       |       | mod 256  |
+------+-------+------+------+-------+-------+----------+
checksum = (addr + cmd1 + cmd2 + data1 + data2) mod 256
```

## General response (4 bytes)

Every executed command is answered with `FF <addr> <alarms> <checksum>` — the sync
byte, the address, the alarm byte `00` and as checksum the request checksum plus the
alarm byte, modulo 256 (Fujifilm SX400 Pelco-D spec v1.10.0, 3.2.1). Example:
`FF 01 00 02 20 00 23` (pan right, medium speed) is answered with `FF 01 00 23`, focus
near `FF 01 01 00 00 00 02` with `FF 01 00 02`. Wrong checksum → no reply at all.

## Drive (motion) commands

cmd2 bitmask (bit 0 of cmd2 is always 0 for motion):

| Bit | Meaning |
|---|---|
| 0x02 | pan right |
| 0x04 | pan left |
| 0x08 | tilt up |
| 0x10 | tilt down |
| 0x20 | zoom tele |
| 0x40 | zoom wide |
| 0x80 | focus far |

cmd1 bit 0 (0x01) = focus near, bit 1 (0x02) iris open, bit 2 (0x04) iris close; bits
3–7 are not used by current Pelco-D. Different axes are combinable (diagonal moves,
pan+zoom); contradicting bits of one axis (left+right, up+down, tele+wide,
near+far, open+close) make the command invalid (SX400 spec 5.1.1 note 4).

Runaway detection: a drive command stops by itself after 15 s; a new drive command
restarts the timer (SX400 spec section 4, "Pelco has specified …").

A drive frame describes the **whole motion state**: an axis whose direction bit is
cleared stops — a later zoom-only frame also stops the pan.

Speed fields: data1 = pan speed, data2 = tilt speed, range 0x00–0x3F where 0x00 is the
slowest speed (not a stop) and 0xFF is turbo (maximum). Zoom and focus speeds are not
in the drive frame; they are set with the extended commands below. Speeds map onto the
camera's internal speed ranges.

Stop all: `FF <addr> 00 00 00 00 <chk>`.

## Extended commands (cmd2 bit 0 set, preset number in data2)

| Opcode (cmd2) | Command |
|---|---|
| 0x03 | set preset (save current position as preset n, 0–99) |
| 0x05 | clear preset |
| 0x07 | call preset (moves to preset n; **no response** if not set) |
| 0x25 | set zoom speed (data2 0x00 slowest … 0x03 highest) |
| 0x27 | set focus speed (data2 0x00 slowest … 0x03 highest) |

Focus commands only move in manual focus mode; while autofocus is on they are ignored
(like VISCA manual focus).

## Parser rules (resync)

- Resync on the sync byte 0xFF: garbage before it is dropped.
- A 7-byte candidate with a wrong checksum is discarded byte by byte (only its sync
  byte), so a stray 0xFF cannot swallow a following valid frame.

## Notes

- Presets are the same 100 presets as VISCA/ONVIF (0–99).
- Pelco-D defines position queries (e.g. Query Zoom Position `00 55` → response
  `00 5D <MSB> <LSB>`), which ptzsim does not implement yet — read the position via
  VISCA/ONVIF on the same camera.
- Official specs: Pelco "D" Protocol manual rev 5.x (sections 3–4); Fujifilm SX400/SX1600
  Pelco-D specifications (links in the repository README).
