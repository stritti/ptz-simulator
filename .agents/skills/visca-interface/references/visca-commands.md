<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# VISCA command and inquiry reference

Command set of the classic Sony BRC/EVI and Axis cameras (per the
[Axis VISCA interface description](https://www.axis.com/dam/public/70/3d/31/visca-interface-api-description-en-US-266656.pdf)).
The [Sony ILME-FR7 command list](https://pro.sony/s3/2022/09/14131603/VISCA-Command-List-Version-2.00.pdf)
uses other white-balance codes (`04` = ATW). `8x` = `0x80 | camera address`, replies
come from `90`; commands reply ACK `90 4z FF` + completion `90 5z FF` (for absolute moves
the completion is sent once the axes of that command have reached the target).

## Commands

| Command | Bytes |
|---|---|
| Power on / standby | `8x 01 04 00 02/03 FF` |
| Zoom stop / tele / wide / variable | `8x 01 04 07 00/02/03/2p/3p FF` |
| Zoom direct | `8x 01 04 47 0p 0q 0r 0s FF` |
| Focus stop / far / near / variable | `8x 01 04 08 00/02/03/2p/3p FF` |
| Focus direct | `8x 01 04 48 0p 0q 0r 0s FF` |
| Auto focus / manual / toggle | `8x 01 04 38 02/03/10 FF` |
| One push AF | `8x 01 04 18 01 FF` |
| White balance mode (00 auto, 01 indoor, 02 outdoor, 04 auto outdoor, 05 manual) | `8x 01 04 35 0p FF` |
| Red / blue gain, relative and absolute | `8x 01 04 03/04 0p FF`, `8x 01 04 43/44 00 00 0p 0q FF` |
| One push white balance | `8x 01 04 10 05 FF` |
| Preset reset / set / recall (pp hex 00…63 = 0…99) | `8x 01 04 3F 00/01/02 pp FF` |
| Preset speed select (1 separate, 2 common) | `8x 01 7E 04 1B 0p FF` |
| Common preset speed (01…32 hex) | `8x 01 7E 04 1C 0p 0p FF` |
| Separate preset speed (01…32 hex) | `8x 01 7E 01 0B pp qq FF` |
| Pan/tilt drive (VV pan speed, WW tilt speed, XX pan dir, YY tilt dir) | `8x 01 06 01 VV WW XX YY FF` |
| Pan/tilt absolute / relative | `8x 01 06 02/03 VV WW 0Y0Y0Y0Y 0Z0Z0Z0Z FF` |
| Home / reset | `8x 01 06 04 FF` / `8x 01 06 05 FF` |
| Command cancel (z = socket) | `8x 2z FF` |
| IF_Clear | `8x 01 00 01 FF`, broadcast `88 01 00 01 FF` |
| Address set (takes address w, answers `88 30 0w+1 FF`) | `88 30 0w FF` |

Pan/tilt drive directions: pan `01` = left, `02` = right, `03` = stop; tilt `01` = up,
`02` = down, `03` = stop. Diagonals combine the direction nibbles.

## Inquiries (reply `90 50 ... FF`)

| Inquiry | Command | Reply payload after `90 50` |
|---|---|---|
| Power | `09 04 00` | `0p` (02 on, 03 standby) |
| Zoom position | `09 04 47` | `0p 0q 0r 0s` |
| Focus position | `09 04 48` | `0p 0q 0r 0s` |
| Focus mode | `09 04 38` | `0p` (02 auto, 03 manual) |
| White balance mode | `09 04 35` | `0p` |
| Preset speed select | `09 7E 04 1B` | `0p` |
| Common preset speed | `09 7E 04 1C` | `0p 0p` |
| Separate preset speed | `09 7E 01 0B pp` (pp = preset number) | `qq` (speed of preset pp) |
| Pan/tilt position | `09 06 12` | `0Y0Y0Y0Y 0Z0Z0Z0Z` (pan, tilt) |
| Max pan/tilt speed | `09 06 11` | `0V 0W` |
| Pan/tilt status | `09 06 10` | two status bytes (see transports reference) |
| Version | `09 00 02` | vendor, model, ROM version, socket number |

Full command bytes carry the header: e.g. position inquiry to camera 1 is
`81 09 06 12 FF`, reply `90 50 0Y0Y0Y0Y 0Z0Z0Z0Z FF`.
