<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# Running the ptzsim reference simulator

ptzsim simulates one PTZ camera speaking VISCA and ONVIF. Python 3.8+, standard library
only (NDI needs the optional `ndi` extra).

## Install / run

```bash
pipx install ptzsim            # or: uvx ptzsim … / uv tool run ptzsim …
python3 -m ptzsim serve …      # from a source checkout (uv run ptzsim … or plain python3)
# single file, nothing to install: download ptzsim.pyz from the GitHub releases
python3 ptzsim.pyz serve …
```

## Serve the protocols your interface speaks

```bash
python3 -m ptzsim serve --sony --tcp --udp --no-tui        # VISCA: UDP 52381, TCP 5678, UDP 1259
python3 -m ptzsim serve --pty /tmp/ttyPTZ                  # VISCA serial via pseudo terminal
python3 -m ptzsim serve --pelco-d /tmp/ttyPelcoD           # Pelco-D serial (0.4.0+); --pelco-d-address 1..255
uv run --extra ndi ptzsim serve --ndi --name "Camera 1"   # NDI source with PTZ metadata (needs the ndi extra)
python3 -m ptzsim serve --onvif --onvif-user admin --onvif-password secret --name "Camera 1"
python3 -m ptzsim serve --onvif 8081 --name "Camera 2"    # several instances = several cameras
python3 -m ptzsim serve --sony --onvif --instant --no-tui  # moves complete at once
```

- ONVIF: HTTP on port 8080 by default (80 needs root), endpoints
  `/onvif/device_service`, `/onvif/media_service`, `/onvif/ptz_service`,
  `/onvif/imaging_service`; WS-Discovery on UDP 3702 (use `--no-discovery` to disable,
  `--advertise-host <IP>` when the advertised address must differ).
- `--onvif-auth digest|wsse|both` selects the accepted auth mechanism.
- The dashboard (default TUI) shows position, motion, presets and the command log;
  `--no-tui` logs instead, `--view-only` is read-only.

## Send commands by hand

```bash
python3 -m ptzsim send "81 01 06 04 FF"                     # home (Sony VISCA/IP, UDP 52381)
python3 -m ptzsim send --proto tcp "81 01 04 3F 01 05 FF"   # store preset 5 (raw TCP 5678)
python3 -m ptzsim send "81 09 06 12 FF"                     # query pan/tilt position
```

## Test your client against ptzsim

- VISCA client: enter the simulator's IP and port (52381 Sony VISCA/IP, 5678 raw TCP,
  1259 raw UDP) or `/tmp/ttyPTZ` as the serial port.
- ONVIF client: let it discover via WS-Discovery (`dn:NetworkVideoTransmitter`, XAddr
  `http://<ip>:8080/onvif/device_service`, scope `onvif://www.onvif.org/name/<name>`), or
  enter the address directly; use the `--onvif-user`/`--onvif-password` credentials.
  In Docker/WSL where multicast fails, enter the address directly. With WSL 2 NAT
  networking, unicast UDP (VISCA/IP 52381, raw UDP 1259, WS-Discovery 3702) is not
  reachable from the LAN either: use `networkingMode=mirrored` or the Windows Python.
- NDI: `uv run --extra ndi pytest -k ndi` in the ptzsim repo runs a real NDI round
  trip (a receiver calls the SDK PTZ functions against `ptzsim serve --ndi`); drive
  the source from NDI Studio Monitor, vMix or OBS (DistroAV).
- With the real client library `onvif-zeep(-async)` (same WSDLs as onvif-zeep):
  in the ptzsim repo, `PTZSIM_ONVIF_CLIENT=1 uv run --group onvif-client pytest` runs the
  suite against it; in your own project, point onvif-zeep at
  `http://127.0.0.1:8080/onvif/device_service` with digest or WSSE credentials.

## Use ptzsim inside your own test suite

`ptzsim.testing` starts the plugins exactly like `ptzsim serve`:

```python
import asyncio
from ptzsim.testing import free_port, serve

async def run():
    port = free_port()
    async with serve("--sony", str(port)) as ctx:   # same argv as `ptzsim serve`
        # talk to 127.0.0.1:port with your client here, then assert on the model:
        assert ctx.state.pan_degrees == 0
    return ctx  # ctx.args: parsed serve options, ctx.ports(): service name -> port

asyncio.run(run())
```

`serve()` is an async context manager that starts the selected plugins on 127.0.0.1
(moves finish at once by default); `free_port()` returns a free port (TCP by default,
`free_port(socket.SOCK_DGRAM)` for UDP). Tests that need optional packages must skip
cleanly (`pytest.importorskip` / env-var skipif).

### Client-side assertions (ptzsim >= 0.7.0)

When your code is the client, drive ptzsim with it and assert on the camera model; this
catches the pitfalls of the checklist section "Client side":

```python
from ptzsim.testing import assert_no_errors, assert_stopped, moving_axes, rejected, serve

async with serve("--onvif", str(port), "--no-discovery") as ctx:
    await my_client.zoom_in(); await my_client.pan_left(); await my_client.stop()
    assert_stopped(ctx.camera.state)          # no axis may keep moving after Stop
    assert_stopped(ctx.camera.state, ["zoom"])  # or only the axes set to speed 0
    assert_no_errors(ctx.camera)              # no VISCA error, control error or fault
```

- `moving_axes(state)` lists the axes (`pan`, `tilt`, `zoom`, `focus`) with a running
  velocity or a pending absolute target; `assert_stopped(state, axes)` fails naming them.
- `rejected(camera)` returns the rejected commands from the command log: VISCA errors
  (e.g. `90 60 02 FF` for tilt speed `0x18`), VISCA over IP control errors `0F 01` /
  `0F 02`, ONVIF faults, invalid Pelco-D frames; `assert_no_errors(camera)` fails on any.
  The same entries appear in red in the dashboard's command log and in the `--no-tui` log.
- Pass `instant=False` to `serve()` when the client must see moves take time (e.g. to
  test that it waits for the VISCA completion).

## Smoke-test your own camera-side endpoint

Use the scripts bundled with the protocol skills:

```bash
python3 visca_conformance.py --host <ip> --transport sony            # UDP 52381
python3 visca_conformance.py --host <ip> --transport tcp --port 5678
python3 onvif_conformance.py --host <ip> --port 8080 [--user u --password p] [--discovery]
```

Both exit 0 only when every wire-level check passes (see the conformance checklist).
