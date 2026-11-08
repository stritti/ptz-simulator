<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# NDI PTZ metadata reference

Transport: XML metadata frames on the NDI stream (no separate control socket).
Discovery: NDI's own (mDNS on Linux). One metadata frame = one XML element.

## Capabilities announcement (sent by the source as metadata)

```xml
<ndi_capabilities ntk_ptz="true" ntk_pan_tilt="true" ntk_zoom="true" ntk_focus="true" ntk_autofocus="true" ntk_white_balance="true" ntk_preset_speed="true"/>
```

## PTZ commands (receiver → source, as metadata)

| Element | Attributes | Effect | Range |
|---|---|---|---|
| `<ntk_ptz_pan_tilt/>` | `pan`, `tilt` | absolute pan/tilt | −1…+1 each (−1 left / bottom, +1 right / top) |
| `<ntk_ptz_pan_tilt_speed/>` | `pan_speed`, `tilt_speed` | continuous move | −1…+1; **+1 pan_speed = moving left** (sign flip vs. absolute pan), +1 tilt_speed = up; 0 stops the axis |
| `<ntk_ptz_zoom/>` | `zoom` | absolute zoom | 0…1 (0 = zoomed in, 1 = zoomed out) |
| `<ntk_ptz_zoom_speed/>` | `zoom_speed` | move zoom | −1…+1 (+1 = inwards/tele, −1 = outwards/wide); 0 stops |
| `<ntk_ptz_focus/>` | `mode="auto"` or `mode="manual" distance="d"` | focus mode / focus to distance | distance 0…1 (0 = infinity, 1 = close) |
| `<ntk_ptz_focus_speed/>` | `distance` | move focus | −1…+1; 0 stops; implies manual focus |
| `<ntk_ptz_store_preset/>` | `index` | save current position as preset | 0…99 |
| `<ntk_ptz_recall_preset/>` | `index`, optional `speed` | move to preset | index 0…99 (unset → ignored/failed), speed 0…1 (default 1) |
| `<ntk_ptz_white_balance/>` | `mode="auto"\|"indoor"\|"outdoor"\|"one_shot"`, or `mode="manual" red="r" blue="b"` | white balance | red/blue 0…1 (0.5 = neutral) |
| `<ntk_ptz_exposure/>`, `<ntk_ptz_iris/>`, `<ntk_ptz_flip/>` | any | accepted and logged, not simulated by the reference | – |

## Behaviour rules

- Unknown `ntk_ptz*` tags and missing/invalid attributes are **ignored** (not
  executed) — the reference logs them and sends nothing back.
- Out-of-range values are clamped to the ranges (the reference clamps via
  `clamp(value, low, high)`).
- No per-command acknowledgement exists (metadata is best-effort); receivers read
  state via their own means.
- Presets are shared with VISCA/ONVIF/Pelco-D: 0…99, wire-identical.

## Resources

- NDI "PTZ and Control Messages": https://docs.ndi.video/all/developing-with-ndi/ndi-metadata/ptz-and-control-messages
- NDI SDK & developer portal: https://ndi.video/developer/
- ndi-python (ships the NDI runtime): https://pypi.org/project/ndi-python/
  (NDI® is a trademark of Vizrt NDI AB; the runtime is subject to the NDI license terms)
