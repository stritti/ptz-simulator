---
layout: home
hero:
  name: ptzsim
  text: A PTZ camera for your test bench.
  tagline: Test camera control without camera hardware. Connect over ONVIF, VISCA or NDI and watch the same simulated camera respond.
  actions:
    - theme: brand
      text: Run the simulator
      link: /guide#running
    - theme: alt
      text: Explore the guide
      link: /guide
---

<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

## Control the camera from your terminal

<figure class="tui-preview">

[![PTZ simulator terminal dashboard showing camera controls, presets, recent commands and a text-mode viewfinder](/images/tui-dashboard.png)](/images/tui-dashboard.png)

<figcaption>
The terminal dashboard combines camera status, presets and a text-mode viewfinder.
Open the image to zoom in.
</figcaption>
</figure>

## Find the landmarks

The camera looks at a landscape with mountains, a house, a UFO beaming up a cow,
billboards with VISCA and ONVIF commands and more, each at fixed pan/tilt
coordinates. Drive your client there and check by eye that it lands where it should.
Some details only show up when you zoom in.

[![Panorama of the simulated scene with the landmarks labelled](/images/scene/panorama.svg)](/scene)

See the [camera scene](/scene) for every viewpoint with its VISCA packets and ONVIF
values.

## One camera, three ways to connect

The simulator shares position, motion and presets across its interfaces, so you
can test a client against the same camera from different protocols.

| Protocol | Interface |
| --- | --- |
| [ONVIF](/guide#onvif-scope) | SOAP over HTTP with WS-Discovery |
| [VISCA](/guide#testing-visca-clients) | Sony VISCA over IP, TCP, UDP or a pseudo terminal |
| [NDI](/guide#ndi) | Optional NDI source with PTZ control and a test picture |

## Start a camera

With Python 3.8 or newer:

```sh
git clone https://github.com/stritti/ptz-simulator.git
cd ptz-simulator
python3 -m ptzsim serve --onvif
```

See the [guide](/guide#running) for more ways to run the simulator, additional
transports and authentication options.
