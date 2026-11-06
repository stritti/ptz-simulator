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
