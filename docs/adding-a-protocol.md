<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# Adding a protocol

ptzsim speaks every control protocol through one small plugin interface. A new
protocol (Pelco-D/P, Panasonic AW, Axis VAPIX, …) is one module with one class;
the command line options, the start-up, the dashboard title and the shutdown
come for free. All protocols drive the same simulated camera, so a move sent via
your protocol shows up in the dashboard, in VISCA inquiries and in ONVIF
`GetStatus`.

- Interface: [`ptzsim/protocol.py`](https://github.com/stritti/ptz-simulator/blob/main/ptzsim/protocol.py)
- Built-in plugins (VISCA, Pelco-D, ONVIF, NDI), good templates:
  [`ptzsim/builtin_protocols.py`](https://github.com/stritti/ptz-simulator/blob/main/ptzsim/builtin_protocols.py)
- Camera model: [`ptzsim/state.py`](https://github.com/stritti/ptz-simulator/blob/main/ptzsim/state.py)
- Test helpers: [`ptzsim/testing.py`](https://github.com/stritti/ptz-simulator/blob/main/ptzsim/testing.py)

## How it fits together

```text
             ptzsim serve --sony --onvif --yourproto
                              │
                 protocol.selected(args) → plugin.start(ctx)
        ┌──────────────┬──────┴───────┬───────────────┐
   SonyViscaIp      Onvif          Ndi          YourPlugin        ← ProtocolPlugin subclasses
   (transports)   (onvif.py)    (ndi.py)      (yourproto.py)       network / serial I/O + parsing
        └──────────────┴──────┬───────┴───────────────┘
                     ctx.camera (ViscaCamera)                       shared camera, command log
                     ctx.state  (CameraState)                       position, motion, presets
                     ctx.simulator (Simulator)                      motor physics, tick loop
```

| Piece | What it is | What your protocol uses |
|-------|------------|-------------------------|
| `ProtocolPlugin` | base class of a protocol | `name`, `title`, `add_arguments`, `enabled`, `start`, `stop` |
| `PortPlugin` | `ProtocolPlugin` switched on by `--<name> [PORT]` | `default_port`, `help`, `port(args)`, `add_options` |
| `ServeContext` (`ctx`) | handed to `start()` | `ctx.state`, `ctx.camera`, `ctx.host`, `ctx.name`, `ctx.args`, `ctx.simulator` |
| `Endpoint` | an address shown in the dashboard title (and its port in the network view) | `Endpoint(label, address, port, service="")` |
| `register` | class decorator | makes the plugin known to `ptzsim serve` |
| `CameraState` | the camera model, in VISCA units | `move_pan_tilt_to`, `drive_pan_tilt`, `zoom_to`, `drive_zoom`, `stop_all`, `save_preset`, `recall_preset`, `pan_degrees`, … |
| `ViscaCamera` | owns the state and the command log | `camera.record(label, text, ok)`, `camera.instant` |

The camera model keeps positions in VISCA units (pan ±2448, tilt −432…1296,
zoom 0…0x4000, 14.4 units per degree, limits in `state.py`). Your protocol
converts its own units to these. `onvif.py` (`pan_from_onvif`, …) and `ndi.py`
show conversions from normalised −1…1 ranges.

## Step by step

The example below is a deliberately tiny, made-up protocol ("TEXT": one ASCII
command per line over TCP). It is not a real camera protocol, but it has every
part a real one needs. The code block is executed by
[`tests/test_protocol.py`](https://github.com/stritti/ptz-simulator/blob/main/tests/test_protocol.py),
so it is guaranteed to work.

### 1. Separate parsing from I/O

Write a class that turns one message into actions on `camera.state` and returns
the reply bytes or text. Keep sockets out of it, so it can be unit-tested
without a network (compare `ViscaCamera.handle` and `NdiPtzController.handle`).

- Validate exactly as the standard says and answer errors the way the standard
  defines them. ptzsim exists to test clients against the protocol, so do not be
  lenient where the specification is strict, and note deliberate deviations in
  the README.
- Call `camera.record(label, description, ok)` for every command, so it appears
  in the dashboard log.
- If `camera.instant` is set (`--instant`), call `state.finish_moves()` after a
  move so it completes at once.

### 2. Write the plugin

Subclass `PortPlugin` for the usual "`--<name> [PORT]`" option, or
`ProtocolPlugin` for anything else (see `ViscaSerial` and `Ndi` in
`builtin_protocols.py`). In `start()`:

- open the server on `ctx.host` and append it to `self.servers` (closed
  automatically on shutdown),
- return one `Endpoint` per address you listen on.

Extra options go into `add_options()` (or `add_arguments()` for a
`ProtocolPlugin`); name them `--<name>-…` so they cannot clash with other
protocols. They appear under the plugin's `title` in `ptzsim serve --help`.
Override `stop()` (and call `super().stop()`) if the protocol says goodbye on
shutdown, like the ONVIF WS-Discovery `Bye`.

<!-- example: text_protocol.py -->
```python
"""TEXT: a made-up line protocol over TCP, as an example plugin."""

from __future__ import annotations

import asyncio
from typing import List

from ptzsim import state as st
from ptzsim.protocol import Endpoint, PortPlugin, ServeContext, register


class TextController:
    """Protocol logic: one command line in, one reply line out; no sockets here."""

    def __init__(self, camera):
        self.camera = camera  # the shared ViscaCamera; the camera model is camera.state

    def handle(self, line: str) -> str:
        words = line.split()
        command, params = (words[0].upper(), words[1:]) if words else ("", [])
        state = self.camera.state
        try:
            if command == "GOTO":  # GOTO <pan degrees> <tilt degrees>
                pan, tilt = (float(p) * st.UNITS_PER_DEGREE for p in params)
                state.move_pan_tilt_to(pan, tilt, st.PAN_SPEED_MAX, st.TILT_SPEED_MAX)
            elif command == "ZOOM":  # ZOOM <0..1>, 0 is wide
                zoom = st.clamp(float(params[0]), 0.0, 1.0)
                state.zoom_to(st.ZOOM_MIN + zoom * (st.ZOOM_MAX - st.ZOOM_MIN))
            elif command == "STOP":
                state.stop_all()
            elif command == "POS?":  # inquiries are not logged
                return f"POS {state.pan_degrees:.1f} {state.tilt_degrees:.1f} {state.zoom_ratio:.1f}"
            else:
                raise ValueError(f"unknown command {command!r}")
        except (ValueError, IndexError) as err:  # bad number or wrong parameter count
            self.camera.record("TEXT", f"{line.strip()!r}: {err}", ok=False)
            return f"ERR {err}"
        if self.camera.instant:
            state.finish_moves()
        self.camera.record("TEXT", line.strip())
        return "OK"


@register
class TextProtocol(PortPlugin):
    name = "text"  # unique id and option: --text [PORT]
    title = "TEXT example protocol"  # heading in --help
    default_port = 4000
    help = "made-up line protocol over TCP (default port {port})"

    async def start(self, ctx: ServeContext) -> List[Endpoint]:
        controller = TextController(ctx.camera)
        port = self.port(ctx.args)

        async def client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    line = await reader.readline()
                    if not line:
                        break
                    reply = controller.handle(line.decode("ascii", "replace"))
                    writer.write(reply.encode("ascii") + b"\r\n")
            except ConnectionError:
                pass
            finally:
                writer.close()

        self.servers.append(await asyncio.start_server(client, ctx.host, port))
        return [Endpoint("TEXT", f"tcp://{ctx.host}:{port}", port)]
```

### 3. Register the module

- **In ptzsim itself:** save the module as `ptzsim/<name>.py` and add
  `"ptzsim.<name>"` to `EXTRA_MODULES` in `ptzsim/protocol.py`. Plugins appear
  in the order they are registered. Use only the standard library (see
  [AGENTS.md](https://github.com/stritti/ptz-simulator/blob/main/AGENTS.md#constraints));
  a protocol that needs a third-party package imports it inside `start()` and
  gets its own extra in `pyproject.toml`, like NDI.
- **As a separate package:** declare an entry point, nothing in ptzsim changes:

  ```toml
  [project.entry-points."ptzsim.protocols"]
  text = "my_package.text_protocol:TextProtocol"
  ```

  The entry point may name the plugin class or a module that calls `register`.
  A plugin that fails to load is skipped with a warning.

Then:

```console
$ uv run ptzsim serve --text --no-tui
$ printf 'GOTO 10 5\r\nPOS?\r\n' | nc 127.0.0.1 4000
OK
POS 10.0 5.0 1.0
```

### 4. Test it

Test the parser directly (fast, no sockets), and once end to end with
`ptzsim.testing.serve`, which starts the plugins exactly as
`ptzsim serve <options>` would, on 127.0.0.1:

```python
import asyncio
import socket

from ptzsim.testing import free_port, serve


def test_goto_over_tcp():
    async def run():
        port = free_port()
        async with serve("--text", str(port)) as ctx:
            def talk():
                with socket.create_connection(("127.0.0.1", port), timeout=1) as sock:
                    sock.sendall(b"GOTO 10 5\r\n")
                    return sock.recv(64)

            reply = await ctx.loop.run_in_executor(None, talk)
            return ctx, reply

    ctx, reply = asyncio.run(run())
    assert reply == b"OK\r\n"
    assert round(ctx.state.pan_degrees) == 10
```

`tests/test_protocol.py` also checks every registered plugin against the
interface (unique name, options under its own heading, off by default), so a new
plugin is covered as soon as it is registered.

### 5. Document it

- `README.md`: add the option to "Supported transports", and a section with the
  supported commands and the deliberate limitations (see "ONVIF scope").
- `AGENTS.md`: add the module to "Architecture".
- Commit as `feat(<name>): …` (Conventional Commits, see AGENTS.md).

## Checklist for a real protocol

- [ ] Framing exactly as specified (sync bytes, length, checksum; streams may
      split or join messages, see `visca.split_packets`).
- [ ] Addressing: answer only your own address (and broadcasts if the protocol
      has them).
- [ ] Unit conversion to `CameraState` (positions and speeds), clamped to the
      limits in `state.py`.
- [ ] Replies and error replies byte for byte as in the specification,
      including when a reply is sent (immediately or after the move).
- [ ] Serial protocols: reuse the pseudo terminal approach of `serve_pty` in
      `transports.py`.
- [ ] `camera.record(...)` for each command; `camera.instant` honoured.
- [ ] Parser unit tests with the examples from the specification, one end-to-end
      test with `ptzsim.testing.serve`.
- [ ] README and AGENTS.md updated.
