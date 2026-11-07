---
title: VISCA
---

<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# VISCA

References: **Sony VISCA Command List Version 2.00** (ILME-FR7, cited as *Sony*) with
its chapter "VISCA over IP", and the **Axis VISCA interface description** (cited as
*Axis*) for the classic 4-digit BRC/EVI command set. Both are vendor documents that may
not be redistributed; read them from the official links on the
[overview page](./). ptzsim module: `ptzsim/visca.py`, options `--sony`, `--tcp`,
`--udp`, `--pty`.

VISCA is not one standard: the transport and the replies are common to Sony
cameras, the command set differs per model. ptzsim follows the classic Sony
BRC/EVI and Axis command set.

## Framing and replies

| Source | Requirement | ptzsim |
|---|---|---|
| Sony, Axis | message `8x … FF`, x = camera address 1–7 | yes; serial uses `--address` |
| Sony "ACK/Completion Messages" | ACK `y0 4z FF` on acceptance, completion `y0 5z FF` after execution, z = socket | yes; the completion of an absolute move comes once its axes reach the target |
| Sony "Inquiry Packet" | inquiries answer `y0 50 … FF` without ACK | yes |
| Sony "Error Messages" | syntax error `y0 60 02 FF`, buffer full `y0 60 03 FF`, canceled `y0 6z 04 FF`, no socket `y0 6z 05 FF`, not executable `y0 6z 41 FF` | yes |
| Sony "Socket" | two command sockets; a command holds its socket until it completes | yes; a third command while both are busy gets "buffer full" |
| Sony | command cancel `8x 2z FF` | yes |
| Sony | IF_Clear `8x 01 00 01 FF` answers `y0 50 FF`, stops motion and empties the sockets | yes, also as broadcast `88 01 00 01 FF` |
| Sony | address set `88 30 0w FF` answers `88 30 0w+1 FF` | yes |

## VISCA over IP

| Source | Requirement | ptzsim |
|---|---|---|
| Sony "VISCA over IP" | UDP port 52381, 8-byte header: payload type (2), length (2), sequence number (4) | yes (`--sony`) |
| Sony | payload types `01 00` command, `01 10` inquiry, `01 11` reply, `02 00` control command, `02 01` control reply | yes |
| Sony | control command RESET `02 00 … 01` resets the sequence number, answered with ACK `01` | yes |
| Sony | replies carry the sequence number of the request | yes |
| Sony | control replies `0F 01` (sequence number error) and `0F 02` (message error, e.g. wrong payload type) | yes |
| Sony | a message answered with an error was not performed, so its retransmission is executed | yes |
| Sony | the VISCA address over IP is fixed: replies come from `90` | yes |

## Commands

| Source | Command | ptzsim |
|---|---|---|
| Axis "Command list: camera" | power, zoom (stop/tele/wide/variable/direct `0000`–`4000`), focus (stop/far/near/variable/direct `1000`–`F000`), auto/manual focus, one push AF | yes |
| Axis, Sony | white balance mode, red/blue gain (relative and direct), one push WB | yes; the Sony list uses other mode codes (`04` = ATW) |
| Sony | presets reset/set/recall `pp` = hex `00`–`63` (100 presets) | yes |
| Sony | preset speed select, common and separate preset speed `01`–`32` | yes |
| Axis "Command list: pan/tilt" | pan/tilt drive, absolute and relative position, home, reset | yes; 4- and 5-digit positions; reset does not run a calibration move (issue #14) |
| Sony | manual focus while autofocus is on is "not executable" | yes |

## Inquiries

Power, zoom, focus, focus mode, white balance mode, preset speeds, pan/tilt position,
pan/tilt maximum speed, pan/tilt status and version are answered as listed in the
Sony inquiry command list.

## Known gaps

- Serial replies always come from address `90`, even to a controller that is not
  address 0 (issue #12).
- No strict check that every data nibble has the form `0p`, and no check of the
  VISCA over IP length field against the payload (issue #13).
