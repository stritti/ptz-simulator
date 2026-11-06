---
title: Camera scene
---

<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# Camera scene

The simulated camera looks at a landscape with landmarks at fixed pan/tilt
positions. Drive the camera there from your client and you should see the same
picture as below, in the NDI test picture and in the TUI viewfinder. If you see
something else, the client converts coordinates differently than the camera.

![Panorama of the simulated scene from pan −200° to +200° with the landmarks labelled](/images/scene/panorama.svg)

The panorama shows the whole reachable scene: pan −170° to +170° (dashed lines)
plus half of the 60° field of view on each side, tilt −30° to +90°. Red posts mark
every 45° of pan, the horizon is at 0° tilt.

## Coordinates

Pan and tilt are camera angles in degrees: pan grows to the right, tilt grows
upwards. Zoom is the optical zoom ratio, 1× (60° field of view) to 20× (3°).

| Value | VISCA | ONVIF generic space |
| --- | --- | --- |
| Pan | 14.4 units per degree, ±2448 (≈ ±170°) | x = pan / 170°, −1 … 1 |
| Tilt | 14.4 units per degree, −432 … 1296 (−30° … +90°) | y = tilt / 30° below, tilt / 90° above the horizon |
| Zoom | 0x0000 (1×) … 0x4000 (20×), linear in the ratio | 0 … 1 |

The table lists a viewpoint for every landmark. Entries marked ↳ are details that
need more zoom.

<!-- scene-table:start -->
| Landmark | Pan | Tilt | Zoom | ONVIF x / y / zoom |
|---|---|---|---|---|
| [Alps](#alps) | 80° | 6° | 1× | 0.4706 / 0.0664 / 0.0000 |
| ↳ [Summit cross](#summit) | 78.2° | 14.1° | 20× | 0.4600 / 0.1566 / 1.0000 |
| [Forest](#forest) | −18° | 4° | 1.5× | -0.1058 / 0.0448 / 0.0263 |
| ↳ [Fox](#fox) | −14.3° | 0.4° | 10× | -0.0842 / 0.0046 / 0.4737 |
| [House](#house) | −95° | 5° | 1.5× | -0.5588 / 0.0556 / 0.0263 |
| [Sun](#sun) | −50° | 32° | 2× | -0.2941 / 0.3557 / 0.0526 |
| [Flock of birds](#birds) | 22° | 24° | 2× | 0.1295 / 0.2670 / 0.0526 |
| ↳ [Straggler](#straggler) | 17.8° | 24.7° | 15× | 0.1046 / 0.2747 / 0.7368 |
| [Plane with banner](#plane) | 48° | 35.5° | 2.5× | 0.2823 / 0.3943 / 0.0789 |
| [UFO](#ufo) | 140° | 10° | 1.5× | 0.8235 / 0.1111 / 0.0263 |
| ↳ [Abducted cow](#cow) | 140° | 6° | 5× | 0.8235 / 0.0664 / 0.2105 |
| [Hot-air balloon](#balloon) | −140° | 24° | 2× | -0.8235 / 0.2670 / 0.0526 |
| [Lake](#lake) | −60° | −9° | 2× | -0.3529 / -0.3009 / 0.0526 |
| ↳ [Rubber duck](#duck) | −63° | −7.9° | 12× | -0.3705 / -0.2639 / 0.5789 |
| ↳ [Lake monster](#nessie) | −55° | −10.2° | 8× | -0.3235 / -0.3403 / 0.3684 |
| [VISCA billboard](#visca-sign) | −165° | 2.5° | 4× | -0.9706 / 0.0278 / 0.1579 |
| [ONVIF billboard](#onvif-sign) | 165° | 2.5° | 4× | 0.9706 / 0.0278 / 0.1579 |
| [Rocket](#rocket) | 10° | 63° | 2× | 0.0588 / 0.6998 / 0.0526 |
| [Buried treasure](#treasure) | 30° | −27.5° | 4× | 0.1765 / -0.9167 / 0.1579 |
<!-- scene-table:end -->

## How landmarks are drawn

Each landmark is text art in `ptzsim/scenery.py`. One art character covers a fixed
number of degrees of pan and twice as many of tilt, like a terminal cell. The
viewfinder samples the art for each of its cells. When the camera zooms in further
than the art's own scale, solid characters (rock, water, roof) fill all the cells
they cover, lines stretch along their direction, and letters are drawn once, so text
stays readable. The NDI picture draws the same art with filled blocks, lines and a
3×5 pixel font.

## Landmarks

Each viewpoint gives the VISCA packets (absolute position at pan speed 0x18 and
tilt speed 0x14, then zoom direct) for `ptzsim send` and the ONVIF `AbsoluteMove`
values.

<!-- scene-stops:start -->
### Alps {#alps}

A mountain range with snow caps across 52°–108° of pan. Pan 80°, tilt 6°, zoom 1×.

<div class="scene-shots">

![Alps in the NDI picture](/images/scene/alps-ndi.png)

![Alps in the TUI viewfinder](/images/scene/alps-tui.svg)

</div>

```sh
uv run ptzsim send "81 01 06 02 18 14 00 04 08 00 00 00 05 06 FF" "81 01 04 47 00 00 00 00 FF"
```

ONVIF `AbsoluteMove`: `PanTilt x="0.4706" y="0.0664"`, `Zoom x="0.0000"`.

### Summit cross {#summit}

A climber waves next to the cross on the highest peak. Pan 78.2°, tilt 14.1°, zoom 20×.

<div class="scene-shots">

![Summit cross in the NDI picture](/images/scene/summit-ndi.png)

![Summit cross in the TUI viewfinder](/images/scene/summit-tui.svg)

</div>

```sh
uv run ptzsim send "81 01 06 02 18 14 00 04 06 06 00 00 0C 0B FF" "81 01 04 47 04 00 00 00 FF"
```

ONVIF `AbsoluteMove`: `PanTilt x="0.4600" y="0.1566"`, `Zoom x="1.0000"`.

### Forest {#forest}

Fir trees just left of the 0° post, in view at the home position. Pan −18°, tilt 4°, zoom 1.5×.

<div class="scene-shots">

![Forest in the NDI picture](/images/scene/forest-ndi.png)

![Forest in the TUI viewfinder](/images/scene/forest-tui.svg)

</div>

```sh
uv run ptzsim send "81 01 06 02 18 14 0F 0E 0F 0D 00 00 03 0A FF" "81 01 04 47 00 01 0A 0F FF"
```

ONVIF `AbsoluteMove`: `PanTilt x="-0.1058" y="0.0448"`, `Zoom x="0.0263"`.

### Fox {#fox}

A fox peeks out between the trees. Pan −14.3°, tilt 0.4°, zoom 10×.

<div class="scene-shots">

![Fox in the NDI picture](/images/scene/fox-ndi.png)

![Fox in the TUI viewfinder](/images/scene/fox-tui.svg)

</div>

```sh
uv run ptzsim send "81 01 06 02 18 14 0F 0F 03 02 00 00 00 06 FF" "81 01 04 47 01 0E 05 01 FF"
```

ONVIF `AbsoluteMove`: `PanTilt x="-0.0842" y="0.0046"`, `Zoom x="0.4737"`.

### House {#house}

Smoking chimney, a fence and a cat in the window. Pan −95°, tilt 5°, zoom 1.5×.

<div class="scene-shots">

![House in the NDI picture](/images/scene/house-ndi.png)

![House in the TUI viewfinder](/images/scene/house-tui.svg)

</div>

```sh
uv run ptzsim send "81 01 06 02 18 14 0F 0A 0A 08 00 00 04 08 FF" "81 01 04 47 00 01 0A 0F FF"
```

ONVIF `AbsoluteMove`: `PanTilt x="-0.5588" y="0.0556"`, `Zoom x="0.0263"`.

### Sun {#sun}

The sun wears sunglasses. Pan −50°, tilt 32°, zoom 2×.

<div class="scene-shots">

![Sun in the NDI picture](/images/scene/sun-ndi.png)

![Sun in the TUI viewfinder](/images/scene/sun-tui.svg)

</div>

```sh
uv run ptzsim send "81 01 06 02 18 14 0F 0D 03 00 00 01 0C 0D FF" "81 01 04 47 00 03 05 0E FF"
```

ONVIF `AbsoluteMove`: `PanTilt x="-0.2941" y="0.3557"`, `Zoom x="0.0526"`.

### Flock of birds {#birds}

A V formation flying east. Pan 22°, tilt 24°, zoom 2×.

<div class="scene-shots">

![Flock of birds in the NDI picture](/images/scene/birds-ndi.png)

![Flock of birds in the TUI viewfinder](/images/scene/birds-tui.svg)

</div>

```sh
uv run ptzsim send "81 01 06 02 18 14 00 01 03 0D 00 01 05 0A FF" "81 01 04 47 00 03 05 0E FF"
```

ONVIF `AbsoluteMove`: `PanTilt x="0.1295" y="0.2670"`, `Zoom x="0.0526"`.

### Straggler {#straggler}

One bird lags behind and calls for the others. Pan 17.8°, tilt 24.7°, zoom 15×.

<div class="scene-shots">

![Straggler in the NDI picture](/images/scene/straggler-ndi.png)

![Straggler in the TUI viewfinder](/images/scene/straggler-tui.svg)

</div>

```sh
uv run ptzsim send "81 01 06 02 18 14 00 01 00 00 00 01 06 04 FF" "81 01 04 47 02 0F 02 08 FF"
```

ONVIF `AbsoluteMove`: `PanTilt x="0.1046" y="0.2747"`, `Zoom x="0.7368"`.

### Plane with banner {#plane}

Tows a banner that greets every PTZ client. Pan 48°, tilt 35.5°, zoom 2.5×.

<div class="scene-shots">

![Plane with banner in the NDI picture](/images/scene/plane-ndi.png)

![Plane with banner in the TUI viewfinder](/images/scene/plane-tui.svg)

</div>

```sh
uv run ptzsim send "81 01 06 02 18 14 00 02 0B 03 00 01 0F 0F FF" "81 01 04 47 00 05 00 0D FF"
```

ONVIF `AbsoluteMove`: `PanTilt x="0.2823" y="0.3943"`, `Zoom x="0.0789"`.

### UFO {#ufo}

A flying saucer beams something up from the meadow. Pan 140°, tilt 10°, zoom 1.5×.

<div class="scene-shots">

![UFO in the NDI picture](/images/scene/ufo-ndi.png)

![UFO in the TUI viewfinder](/images/scene/ufo-tui.svg)

</div>

```sh
uv run ptzsim send "81 01 06 02 18 14 00 07 0E 00 00 00 09 00 FF" "81 01 04 47 00 01 0A 0F FF"
```

ONVIF `AbsoluteMove`: `PanTilt x="0.8235" y="0.1111"`, `Zoom x="0.0263"`.

### Abducted cow {#cow}

The cow in the tractor beam. Pan 140°, tilt 6°, zoom 5×.

<div class="scene-shots">

![Abducted cow in the NDI picture](/images/scene/cow-ndi.png)

![Abducted cow in the TUI viewfinder](/images/scene/cow-tui.svg)

</div>

```sh
uv run ptzsim send "81 01 06 02 18 14 00 07 0E 00 00 00 05 06 FF" "81 01 04 47 00 0D 07 09 FF"
```

ONVIF `AbsoluteMove`: `PanTilt x="0.8235" y="0.0664"`, `Zoom x="0.2105"`.

### Hot-air balloon {#balloon}

Red and cream stripes, drifting high. Pan −140°, tilt 24°, zoom 2×.

<div class="scene-shots">

![Hot-air balloon in the NDI picture](/images/scene/balloon-ndi.png)

![Hot-air balloon in the TUI viewfinder](/images/scene/balloon-tui.svg)

</div>

```sh
uv run ptzsim send "81 01 06 02 18 14 0F 08 02 00 00 01 05 0A FF" "81 01 04 47 00 03 05 0E FF"
```

ONVIF `AbsoluteMove`: `PanTilt x="-0.8235" y="0.2670"`, `Zoom x="0.0526"`.

### Lake {#lake}

A lake on the ground in front of the camera. Pan −60°, tilt −9°, zoom 2×.

<div class="scene-shots">

![Lake in the NDI picture](/images/scene/lake-ndi.png)

![Lake in the TUI viewfinder](/images/scene/lake-tui.svg)

</div>

```sh
uv run ptzsim send "81 01 06 02 18 14 0F 0C 0A 00 0F 0F 07 0E FF" "81 01 04 47 00 03 05 0E FF"
```

ONVIF `AbsoluteMove`: `PanTilt x="-0.3529" y="-0.3009"`, `Zoom x="0.0526"`.

### Rubber duck {#duck}

Floats on the lake. Pan −63°, tilt −7.9°, zoom 12×.

<div class="scene-shots">

![Rubber duck in the NDI picture](/images/scene/duck-ndi.png)

![Rubber duck in the TUI viewfinder](/images/scene/duck-tui.svg)

</div>

```sh
uv run ptzsim send "81 01 06 02 18 14 0F 0C 07 05 0F 0F 08 0E FF" "81 01 04 47 02 05 00 0D FF"
```

ONVIF `AbsoluteMove`: `PanTilt x="-0.3705" y="-0.2639"`, `Zoom x="0.5789"`.

### Lake monster {#nessie}

Its humps rise out of the water. Pan −55°, tilt −10.2°, zoom 8×.

<div class="scene-shots">

![Lake monster in the NDI picture](/images/scene/nessie-ndi.png)

![Lake monster in the TUI viewfinder](/images/scene/nessie-tui.svg)

</div>

```sh
uv run ptzsim send "81 01 06 02 18 14 0F 0C 0E 08 0F 0F 06 0D FF" "81 01 04 47 01 07 09 04 FF"
```

ONVIF `AbsoluteMove`: `PanTilt x="-0.3235" y="-0.3403"`, `Zoom x="0.3684"`.

### VISCA billboard {#visca-sign}

Shows the VISCA home command. Pan −165°, tilt 2.5°, zoom 4×.

<div class="scene-shots">

![VISCA billboard in the NDI picture](/images/scene/visca-sign-ndi.png)

![VISCA billboard in the TUI viewfinder](/images/scene/visca-sign-tui.svg)

</div>

```sh
uv run ptzsim send "81 01 06 02 18 14 0F 06 0B 08 00 00 02 04 FF" "81 01 04 47 00 0A 01 0B FF"
```

ONVIF `AbsoluteMove`: `PanTilt x="-0.9706" y="0.0278"`, `Zoom x="0.1579"`.

### ONVIF billboard {#onvif-sign}

Shows the ONVIF home operation. Pan 165°, tilt 2.5°, zoom 4×.

<div class="scene-shots">

![ONVIF billboard in the NDI picture](/images/scene/onvif-sign-ndi.png)

![ONVIF billboard in the TUI viewfinder](/images/scene/onvif-sign-tui.svg)

</div>

```sh
uv run ptzsim send "81 01 06 02 18 14 00 09 04 08 00 00 02 04 FF" "81 01 04 47 00 0A 01 0B FF"
```

ONVIF `AbsoluteMove`: `PanTilt x="0.9706" y="0.0278"`, `Zoom x="0.1579"`.

### Rocket {#rocket}

Straight up at 60° of tilt. Pan 10°, tilt 63°, zoom 2×.

<div class="scene-shots">

![Rocket in the NDI picture](/images/scene/rocket-ndi.png)

![Rocket in the TUI viewfinder](/images/scene/rocket-tui.svg)

</div>

```sh
uv run ptzsim send "81 01 06 02 18 14 00 00 09 00 00 03 08 0B FF" "81 01 04 47 00 03 05 0E FF"
```

ONVIF `AbsoluteMove`: `PanTilt x="0.0588" y="0.6998"`, `Zoom x="0.0526"`.

### Buried treasure {#treasure}

X marks the spot, with a note next to it. Pan 30°, tilt −27.5°, zoom 4×.

<div class="scene-shots">

![Buried treasure in the NDI picture](/images/scene/treasure-ndi.png)

![Buried treasure in the TUI viewfinder](/images/scene/treasure-tui.svg)

</div>

```sh
uv run ptzsim send "81 01 06 02 18 14 00 01 0B 00 0F 0E 07 04 FF" "81 01 04 47 00 0A 01 0B FF"
```

ONVIF `AbsoluteMove`: `PanTilt x="0.1765" y="-0.9167"`, `Zoom x="0.1579"`.
<!-- scene-stops:end -->
