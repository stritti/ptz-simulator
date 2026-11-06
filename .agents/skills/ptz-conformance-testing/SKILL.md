---
name: ptz-conformance-testing
description: Validate a PTZ camera interface implementation (VISCA, ONVIF or other) against the ptzsim reference simulator: start ptzsim with the matching protocol, drive it with ptzsim send or an ONVIF client, or run the bundled visca_conformance.py / onvif_conformance.py smoke scripts against your own camera-side endpoint; follow the conformance checklists for reply framing, error codes, sockets, discovery, auth, faults and timeouts. Use whenever a camera interface must be proven interoperable with real clients/cameras.
license: MIT
compatibility: ptzsim and the bundled scripts need only Python 3.8+ (standard library); optional extras (NDI runtime, onvif-zeep-async client test) are opt-in.
metadata:
  author: stritti
  version: "1.0.0"
  source: https://github.com/stritti/ptz-simulator
---

<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# Conformance testing against the ptzsim reference

[ptzsim](https://github.com/stritti/ptz-simulator) is the reference implementation: it
speaks VISCA (Sony VISCA over IP UDP 52381, raw VISCA over TCP 5678 / UDP 1259, serial
via pty) and ONVIF (Device/Media/PTZ/Imaging SOAP services, WS-Discovery, HTTP digest +
WS-Security) strictly per the standards, on Python 3.8+ with no dependencies. Use it in
both directions:

- **Your code is the camera** (exposes the interface): run the bundled smoke scripts
  against your endpoint —
  `../visca-interface/scripts/visca_conformance.py` (VISCA) and
  `../onvif-ptz-interface/scripts/onvif_conformance.py` (ONVIF). They exit 0 only when
  every wire-level check passes. Also point a real client library at your endpoint.
- **Your code is the client** (drives a camera): start ptzsim and point your client at
  it; compare replies with the checklists below.

References:

- [references/ptzsim-usage.md](references/ptzsim-usage.md) — how to install/run ptzsim,
  the serve/send commands, ports, auth options, and the `ptzsim.testing` helpers for
  end-to-end tests in your own test suite.
- [references/conformance-checklist.md](references/conformance-checklist.md) — what
  "reference-conformant" means per protocol: the exact checks to verify (VISCA framing,
  sockets, error codes; ONVIF spaces, faults, discovery, auth, timeouts) plus the known
  deliberate deviations of the reference.

## Quick start

```bash
# reference camera on localhost: VISCA/IP 52381, raw TCP 5678, raw UDP 1259, ONVIF 8080
python3 -m ptzsim serve --sony --tcp --udp --onvif --onvif-user admin --onvif-password secret --no-tui

# quick VISCA checks against it
python3 -m ptzsim send "81 09 06 12 FF"                 # pan/tilt position inquiry
python3 -m ptzsim send "81 01 06 04 FF"                 # home

# smoke-test YOUR camera-side endpoint instead
python3 visca_conformance.py  --host 192.168.1.50 --transport sony
python3 onvif_conformance.py  --host 192.168.1.50 --port 8080 --user admin --password secret --discovery
```

## Rules for conformance tests

- Test over real sockets end to end, not only parsed fixtures.
- Assert the exact reply bytes/SOAP structure, including error paths (syntax error,
  not executable, buffer full; InvalidArgVal, NoProfile, MovingPTZ, ActionNotSupported).
- Cover discovery (Probe → ProbeMatches with XAddrs) and auth (401 challenge; digest and
  WSSE UsernameToken PasswordDigest) when the interface has them.
- Where the reference deliberately deviates from the full standard, document the
  deviation in your README instead of "fixing" the test (see the checklist).
