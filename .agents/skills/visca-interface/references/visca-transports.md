<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# VISCA transports, replies, sockets and ranges

## Serial (RS-232 / RS-422)

- Baud 9600 or 38400, 8 data bits, no parity, 1 stop bit (8N1).
- Daisy chain of up to 7 cameras; addresses are assigned with the Address Set command
  (`88 30 0w FF` → reply `88 30 0(w+1) FF`).
- Packet: header byte `0x80 | target address` (camera 1 = `0x81`), payload bytes, always
  terminated by `0xFF`.
- Replies come from `(address + 8) << 4`: camera 1 answers with `0x90`, camera 2 with
  `0xA0` (Sony VISCA over IP fixes the address to 1, so replies are always `0x90`).
- Broadcast packets start with `0x88` (e.g. IF_Clear `88 01 00 01 FF`) and get **no ACK**.

## VISCA over IP (Sony, UDP 52381)

8-byte header + VISCA payload, header is big-endian `>HHI`:

```
bytes 0-1   payload type   0x0100 command | 0x0110 inquiry | 0x0120 device setting
                            0x0200 control command | 0x0201 control reply
bytes 2-3   payload length (of the VISCA payload that follows)
bytes 4-7   32-bit sequence number, incremented per message by the controller
bytes 8+    raw VISCA packet (8x ... FF)
```

- The camera answers VISCA replies with payload type `0x0111` and the **sequence number
  of the request**.
- Control command RESET: payload type `0x0200`, payload `01`; answer `0x0201` + `01`
  and reset the stored sequence number.
- A repeated sequence number is not executed again → control reply `0x0201` + `0F 01`.
- Payload type not matching the packet (inquiry sent as command or vice versa) →
  control reply `0x0201` + `0F 02`.
- A message answered with a VISCA error was not performed, so its retransmission with the
  same sequence number **is** executed again (the error clears the stored sequence).
- Over IP the camera address is fixed to 1: any address is accepted, replies always come
  from `0x90`.

## Reply frames (all transports)

| Reply | Bytes | Meaning |
|---|---|---|
| ACK | `90 4z FF` | command accepted, socket z (1 or 2) |
| Completion | `90 5z FF` | command finished (for moves: axes reached target) |
| Inquiry reply | `90 50 ... FF` | answer to an `8x 09 ... FF` inquiry |
| Syntax error | `90 60 02 FF` | malformed packet |
| Command buffer full | `90 60 03 FF` | both sockets busy |
| Not executable | `90 6z 41 FF` | e.g. standby, preset not set, manual focus while AF on |
| Command canceled | `90 6z 04 FF` | `8x 2z FF` performed; no completion follows |
| No socket | `90 6z 05 FF` | cancel of a free socket |
| IF_Clear | `90 50 FF` | stops all motion, empties both sockets, no ACK for broadcast |

## Command sockets

Sony cameras have two command buffers ("sockets"). A command takes the lowest free socket
(`90 41 FF`, then `90 42 FF`) and the socket stays busy until its absolute move, home or
preset recall has finished. A command arriving while both are busy gets `90 60 03 FF`.
A newer move takes over the axes of an older one; an older command left without axes
completes at once. Inquiries and IF_Clear do not use a socket.

## Pan/tilt status inquiry (`81 09 06 10 FF`)

Reply `90 50` + two status bytes + `FF`: pan/tilt status reports "initialization
completes" (`20 00`) plus "operating" (`04 00`) or "operations complete" (`08 00`) and
the end-stop bits.

## Value ranges (classic BRC/EVI/Axis command set)

| Quantity | Range | Notes |
|---|---|---|
| Pan position | −2448 … +2448 | ≈ ±170°, 14.4 units per degree |
| Tilt position | −432 … +1296 | ≈ −30° … +90° |
| Zoom | 0x0000 … 0x4000 | wide … tele, 1× … 20× |
| Focus | 0x1000 … 0xF000 | infinity … near |
| Pan speed | 1 … 0x18 | in drive and absolute/relative moves |
| Tilt speed | 1 … 0x17 | `00` in absolute/relative moves = "same as pan" |
| Presets | 0 … 99 (hex 00…63) | wire value is shown as 1…100 in UIs |
| Preset speed | 1 … 32 (hex 01…20) | common or per-preset |

In absolute/relative moves both 4- and 5-digit coordinates are accepted (classic
BRC/EVI/Axis and newer Sony models).
