---
title: Pelco-D
---

<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# Pelco-D

References: **Pelco PTZ Protocols, D Protocol, Version 5.0.1** (1 April 2008, cited as
*D 5.0.1*) and the **Fujifilm SX400 Pelco-D Protocol Specification v1.10.0** (cited as
*SX400*). The Pelco manual may not be redistributed; ask Pelco for a copy. ptzsim
module: `ptzsim/pelco.py`, option `--pelco-d [LINK]`.

## Frame and checksum

| Section | Requirement | ptzsim |
|---|---|---|
| D 5.0.1 1.4, SX400 3.1 | 7 bytes: `FF addr cmnd1 cmnd2 data1 data2 cksm`, serial 8N1 | yes; the pseudo terminal ignores the baud rate |
| D 5.0.1 3.1.3 | checksum = sum of bytes 2–6 modulo 256 | yes; frames with a wrong checksum are discarded silently |
| D 5.0.1 4.2 | address 1–255 | yes (`--pelco-d-address`); frames for other addresses are ignored, as on an RS-485 bus |

## Responses

| Section | Requirement | ptzsim |
|---|---|---|
| D 5.0.1 4.2, SX400 3.2.1 | General Response: 4 bytes `FF addr alarms cksm`; alarms is bit-coded, cksm = checksum of the command plus the alarms byte | yes, alarms is always `00` (no alarm inputs), so cksm equals the command checksum: `FF 01 00 02 20 00 23` → `FF 01 00 23` |
| D 5.0.1 4.1/5.1 | Extended Response (7 bytes) for queries; ack/nak for commands a unit may not execute | *missing*: no query commands yet |
| D 5.0.1 5.1 | older units send a General Response for any well-formed command, even one they do not understand | *deviation*: unsupported commands get no reply, so a client sees that ptzsim did not execute them |

## Standard commands (motion)

| Section | Requirement | ptzsim |
|---|---|---|
| D 5.0.1 3.1.1 | cmnd2 bits: 1 right, 2 left, 3 up, 4 down, 5 tele, 6 wide, 7 focus far, bit 0 always 0 | yes |
| D 5.0.1 3.1.1 | cmnd1 bits: 0 focus near, 1 iris open, 2 iris close; bits 3–7 (camera on/off, scan, sense) are not used by newer units | focus near yes; iris is acknowledged but *not simulated*; bits 3–7 are not supported (no reply) |
| D 5.0.1 3.1.1 | a set bit starts a function, a cleared bit stops it | yes: a drive frame describes the whole motion state |
| D 5.0.1 3.1.2, SX400 5.1.1 | opposite directions in one frame (e.g. up + down) are an error | yes: the frame is rejected without a reply |
| D 5.0.1 3.1.2 | pan speed `00`–`3F`, turbo `40`; tilt speed `00`–`3F`, no turbo; `00` is very slow, not a stop | yes: `00` is the slowest speed; every value above `3F` (including `40` and `FF`) is the maximum, for tilt too |
| D 5.0.1 3.1.1, SX400 4 | runaway protection: motion stops after about 15 s without a new motion command | yes, 15 s; the timer only stops motion the Pelco drive started |

## Extended commands

| Section | Command | ptzsim |
|---|---|---|
| D 5.0.1 5.2 | Set Preset `00 03 00 id` | yes, presets 0–99 shared with VISCA/ONVIF |
| D 5.0.1 5.3 | Clear Preset `00 05 00 id` | yes |
| D 5.0.1 5.4 | Go To Preset `00 07 00 id`; an invalid preset is ignored, a motion command aborts the move | yes; an unset preset gets no reply |
| D 5.0.1 5.19, SX400 5.2.1 | Set Zoom Speed `00 25 00 0..3` (0 slowest, 3 fastest) | yes; zoom drives use this speed (default 3) |
| D 5.0.1 5.20, SX400 5.2.2 | Set Focus Speed `00 27 00 0..3` | yes (default 2) |
| D 5.0.1 5.38–5.40 | Set Pan/Tilt/Zoom Position `00 4B` / `4D` / `4F` | *missing* |
| D 5.0.1 5.41–5.47 | Query Pan/Tilt/Zoom Position `00 51` / `53` / `55`, responses `59` / `5B` / `5D` | *missing*; read the position via VISCA or ONVIF on the same camera |
