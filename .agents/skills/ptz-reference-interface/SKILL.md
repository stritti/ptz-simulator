---
name: ptz-reference-interface
description: "Implement a reference-conformant PTZ camera control interface (VISCA over serial or IP, ONVIF Profile S/T PTZ, or another PTZ protocol) that interoperates with real cameras, VMS and controllers: choose the protocol, implement framing and operations exactly per the standard, and validate the result against the ptzsim reference simulator. Use this skill when a project needs to expose or consume a camera interface for pan/tilt/zoom/presets and the wire behaviour must match the standard."
license: MIT
compatibility: No runtime requirements. The bundled conformance scripts and the ptzsim reference simulator need only Python 3.8+ (standard library).
metadata:
  author: stritti
  version: "1.0.0"
  source: https://github.com/stritti/ptz-simulator
---

<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# Reference-conformant PTZ camera interface

Goal: an interface for pan/tilt/zoom/focus/presets whose **wire behaviour matches the
published standard**, so real clients and real cameras accept it. "Reference-conformant"
here means: byte-exact framing and reply codes (VISCA) or SOAP operations, coordinate
spaces, fault chains and discovery/auth behaviour (ONVIF), validated against a reference
implementation — the [ptzsim](https://github.com/stritti/ptz-simulator) simulator, which
implements VISCA (serial, TCP, UDP, Sony VISCA over IP), ONVIF (Device/Media/PTZ,
WS-Discovery, WS-Security), Pelco-D (serial RS-485, since ptzsim 0.4.0) and NDI PTZ
(XML metadata on the NDI stream, optional `ndi` extra) strictly per the standards.

## Workflow

1. **Choose the protocol** — see [references/protocol-selection.md](references/protocol-selection.md)
   (comparison matrix, default ports, selection guide, official specification links).
   - VISCA (Sony) for broadcast/hardware controllers → skill `visca-interface`
   - ONVIF Profile S/T for VMS/surveillance integrations → skill `onvif-ptz-interface`
   - Pelco-D over RS-485 for legacy surveillance cabling → skill `pelco-d-interface`
   - NDI PTZ metadata for pure NDI workflows (Studio Monitor, vMix, OBS) → skill `ndi-ptz-interface`
2. **Implement** the interface with the matching protocol skill. Keep parsing strictly
   separated from I/O so every message handler is unit-testable without sockets.
   Be strict where the standard is strict (framing, checksums, error codes, ranges);
   document deliberate deviations.
3. **Validate** with skill `ptz-conformance-testing`:
   - camera-side implementation (your code exposes the interface): run the bundled
     `visca_conformance.py` / `onvif_conformance.py` scripts against your endpoint;
   - client-side implementation (your code drives a camera): point your client at a
     running ptzsim and compare behaviour.
4. **Document** supported operations, limits and deviations in the project README.

## Skill map

| Skill | Use when |
|---|---|
| `visca-interface` | Implement/validate a VISCA endpoint or client (RS-232/422, VISCA over IP UDP 52381) |
| `onvif-ptz-interface` | Implement/validate an ONVIF Profile S/T PTZ service (SOAP, WS-Discovery, WS-Security) |
| `pelco-d-interface` | Implement/validate a Pelco-D serial endpoint or client (RS-485, 7-byte frames + checksum) |
| `ndi-ptz-interface` | Implement/validate NDI PTZ (ndi_capabilities + ntk_ptz_* XML metadata on the NDI stream) |
| `ptz-conformance-testing` | Test any camera interface against the ptzsim reference simulator + checklists |

## Ground rules

- Match the standard exactly on the wire; do not be lenient where the spec is strict.
- Answer errors the way the standard defines them (VISCA error replies, ONVIF SOAP faults).
- Keep every command observable (log or expose it) so integrations can be debugged.
- Test over real sockets end to end, not only with parsed fixtures.
