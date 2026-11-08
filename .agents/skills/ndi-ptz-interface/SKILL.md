---
name: ndi-ptz-interface
description: "Implement an NDI PTZ control interface (Vizrt NDI): announce PTZ support via the ndi_capabilities metadata and execute the ntk_ptz_* XML metadata commands receivers send over the NDI stream - pan/tilt and zoom absolute and speed, focus, presets, white balance - with the NDI value ranges (pan/tilt -1..1, zoom 0..1, presets 0..99). Use when building an NDI source with PTZ control or a receiver that drives NDI PTZ; validate the metadata XML with scripts/ndi_metadata_check.py and against the ptzsim reference (--ndi)."
license: MIT
compatibility: Validating metadata XML needs only Python 3.8+ (standard library). A live NDI round trip needs the NDI runtime (optional extra ndi-python) - the reference simulator ptzsim (https://github.com/stritti/ptz-simulator) publishes an NDI source with PTZ via --ndi.
metadata:
  author: stritti
  version: "1.0.0"
  source: https://github.com/stritti/ptz-simulator
---

<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# NDI PTZ interface

NDI carries PTZ control as **XML metadata frames on the NDI stream itself** — no
separate socket. The source announces PTZ support in its capabilities metadata; the
receiver sends `<ntk_ptz_*>` elements as metadata and the source executes them.
The reference simulator ptzsim implements this (`--ndi`, optional `ndi` extra).

Reference: [references/ndi-ptz-metadata.md](references/ndi-ptz-metadata.md) —
capabilities element, every `ntk_ptz_*` command with attributes and value ranges,
error behaviour.

## Implementation rules

1. **Announce** PTZ support in the source metadata:
   `<ndi_capabilities ntk_ptz="true" ntk_pan_tilt="true" ntk_zoom="true" ntk_focus="true" ntk_autofocus="true" ntk_white_balance="true" ntk_preset_speed="true"/>`.
2. **Commands** are single XML elements sent as NDI metadata, e.g.
   `<ntk_ptz_pan_tilt pan="0.5" tilt="-0.2"/>`. Execute the ones you support; unknown
   `ntk_ptz*` elements or missing/invalid attributes must be **ignored, not executed**.
3. **Value ranges** (NDI SDK conventions): pan/tilt −1…+1 (absolute: −1 left … +1
   right, −1 bottom … +1 top; speed: +1 = moving left / +1 = moving up — note the sign
   flip for pan speed), zoom 0…1 (0 = zoomed in, 1 = zoomed out), zoom_speed −1…+1
   (+1 = inwards), focus distance 0…1 (0 = infinity), focus speed −1…+1, presets
   index 0…99 with recall speed 0…1, white balance red/blue 0…1 (0.5 neutral).
4. **Presets** are the same 100 presets (0–99) as VISCA/ONVIF/Pelco-D; recall of an
   unset preset fails/ignored.
5. Values are clamped to the ranges (the reference clamps); a speed of 0 stops the
   axis. Metadata is best-effort/UDP-like: do not expect per-command acknowledgements.
6. Discovery is NDI's own (mDNS on Linux); the PTZ channel needs no extra addressing.

## Validate

Validate metadata XML offline (stdlib only):

```bash
python3 scripts/ndi_metadata_check.py metadata.xml        # or: ... < msg.xml
```

For a live round trip, use the reference simulator and an NDI receiver
(NDI Studio Monitor, vMix, OBS/DistroAV): `ptzsim serve --ndi --name "Camera 1"`
(with `uv run --extra ndi`); in the ptzsim repo, `uv run --extra ndi pytest -k ndi`
runs a real NDI round trip calling the SDK PTZ functions against the simulator.
