---
title: NDI PTZ
---

<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# NDI PTZ

Reference: NDI documentation
["PTZ and Control Messages"](https://docs.ndi.video/all/developing-with-ndi/ndi-metadata/ptz-and-control-messages)
and the NDI SDK header `Processing.NDI.Recv.ex.h` (`NDIlib_recv_ptz_*`). ptzsim
module: `ptzsim/ndi.py`, option `--ndi` (needs the `ndi` extra).

| Message | Attributes and ranges | ptzsim |
|---|---|---|
| `ntk_ptz_pan_tilt` | `pan` −1 (left) … +1 (right), `tilt` −1 (down) … +1 (up) | yes |
| `ntk_ptz_pan_tilt_speed` | `pan_speed` −1 (right) … +1 (left), `tilt_speed` −1 (down) … +1 (up); 0 stops | yes; note that the pan speed sign is the opposite of the pan position sign |
| `ntk_ptz_zoom` | `zoom` 0 (zoomed in) … 1 (zoomed out) | yes |
| `ntk_ptz_zoom_speed` | `zoom_speed` −1 (out) … +1 (in) | yes |
| `ntk_ptz_focus` | `mode="auto"` or `mode="manual" distance=` 0 (infinity) … 1 (closest) | yes |
| `ntk_ptz_focus_speed` | focus speed −1 … +1 | yes; the attribute name is not documented on the NDI page, ptzsim reads the attribute `distance` |
| `ntk_ptz_store_preset` | `index` 0 … 99 | yes, the presets shared with VISCA/ONVIF |
| `ntk_ptz_recall_preset` | `index` 0 … 99, `speed` 0 … 1, default 1 | yes |
| `ntk_ptz_white_balance` | `mode` auto, indoor, outdoor, one_shot, manual (`red`, `blue` 0 … 1) | yes |
| `ntk_ptz_exposure` | `mode` auto/manual, `value`, `gain`, `shutter` | accepted, *not simulated* (issue #27) |

The sender announces PTZ support with connection metadata
`<ndi_capabilities ntk_ptz="true" …/>`. That element is not described on the NDI page;
receivers such as NDI Studio Monitor, vMix and OBS (DistroAV) use it to offer PTZ
control.
