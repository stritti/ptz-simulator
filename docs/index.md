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

<div class="badges">

[![CI](https://img.shields.io/github/actions/workflow/status/stritti/ptz-simulator/ci.yml?branch=main&label=CI)](https://github.com/stritti/ptz-simulator/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/github/actions/workflow/status/stritti/ptz-simulator/pages.yml?branch=main&label=docs)](https://stritti.github.io/ptz-simulator/)
[![Coverage](https://img.shields.io/endpoint?url=https%3A%2F%2Fstritti.github.io%2Fptz-simulator%2Fcoverage.json)](https://github.com/stritti/ptz-simulator/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/stritti/ptz-simulator)](https://github.com/stritti/ptz-simulator/releases/latest)
[![PyPI](https://img.shields.io/badge/dynamic/json?label=pypi&url=https%3A%2F%2Fpypi.org%2Fpypi%2Fptzsim%2Fjson&query=%24.info.version&color=orange&cacheSeconds=300)](https://pypi.org/project/ptzsim/)
[![Python versions](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fstritti%2Fptz-simulator%2Fmain%2Fpyproject.toml)](https://github.com/stritti/ptz-simulator/blob/main/pyproject.toml)
[![License: MIT](https://img.shields.io/github/license/stritti/ptz-simulator)](https://github.com/stritti/ptz-simulator/blob/main/LICENSE)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-fe5196?logo=conventionalcommits&logoColor=white)](https://www.conventionalcommits.org/en/v1.0.0/)

</div>

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

| Protocol | Standard (version) | Interface | Specification |
| --- | --- | --- | --- |
| [ONVIF](/guide#onvif-scope) | Core Spec v26.06, PTZ Service v25.12, Imaging v18.12 | SOAP over HTTP with WS-Discovery | [Core](https://www.onvif.org/specs/2606/ONVIF-Core-Spec-v2606.pdf), [PTZ](https://www.onvif.org/specs/2512/ONVIF-PTZ-Service-Spec-v2512.pdf), [Imaging](https://www.onvif.org/specs/srv/img/ONVIF-Imaging-Service-Spec-v1812.pdf) |
| [VISCA](/guide#testing-visca-clients) | Sony VISCA command list v2.00; VISCA over IP per the Sony manuals | Sony VISCA over IP, TCP, UDP or a pseudo terminal | [Command list v2.00](https://pro.sony/s3/2022/09/14131603/VISCA-Command-List-Version-2.00.pdf), [Axis interface description](https://www.axis.com/dam/public/70/3d/31/visca-interface-api-description-en-US-266656.pdf) |
| [NDI](/guide#ndi) | NDI SDK PTZ metadata (`ntk_ptz_*`) | Optional NDI source with PTZ control and a test picture | [NDI PTZ and control messages](https://docs.ndi.video/all/developing-with-ndi/ndi-metadata/ptz-and-control-messages) |

The full list of supported standards with versions and references is in the
guide under [supported standards](/guide#supported-standards).

## Start a camera

With Python 3.8 or newer:

```sh
git clone https://github.com/stritti/ptz-simulator.git
cd ptz-simulator
python3 -m ptzsim serve --onvif
```

See the [guide](/guide#running) for more ways to run the simulator, additional
transports and authentication options.
