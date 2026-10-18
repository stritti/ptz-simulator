# ptzsim — Agent Instructions

Command-line PTZ camera simulator (ONVIF, VISCA, NDI) used to test the PTZ control of
the sibling `../streaming-server` (branch `feature/ptz-control`) without a real camera.
User-facing docs are in [README.md](README.md); keep it in sync with every change to
options, ports or commands.

## Tooling: uv

The project is managed with [uv](https://docs.astral.sh/uv/). Do not use `pip` or a
hand-made venv.

| Command | Purpose |
|---------|---------|
| `uv sync` | Create/update `.venv` from `uv.lock` (includes the `dev` group) |
| `uv run pytest` | Run the test suite |
| `PTZSIM_ONVIF_CLIENT=1 uv run --group onvif-client pytest` | Also run the test against the real ONVIF client (`onvif-zeep-async`) |
| `uv run --extra ndi pytest` | Also run the real NDI round trip (needs the NDI runtime) |
| `uv run ptzsim serve --onvif` | Start the simulator as the streaming-server talks to it |
| `uv add <pkg>` / `uv add --group dev <pkg>` | Add a dependency; commit `pyproject.toml` and `uv.lock` together |

### Verification (must pass after every change)

```sh
uv run pytest
```

Run the `onvif-client` variant as well whenever `ptzsim/onvif.py` changes.

## Constraints

- **Runtime is standard library only.** ONVIF and VISCA must keep working with plain
  `python3 -m ptzsim` and no installed packages. Third-party packages go into the
  `ndi` extra (runtime, optional) or a dependency group (dev/test only).
- `requires-python = ">=3.8"`: no syntax or stdlib APIs newer than 3.8
  (`from __future__ import annotations` is used for type hints).
- Tests that need optional packages must skip cleanly (`pytest.importorskip` or an
  env-var `skipif`), so `uv run pytest` passes on a bare setup.

## Architecture

- `ptzsim/state.py` — `CameraState`: the shared camera model (position, motion at motor
  speed, presets) in VISCA units, with the position limits as module constants.
- `ptzsim/visca.py` — `ViscaCamera`: VISCA command parser on top of `CameraState`; the
  other protocols drive the same `ViscaCamera` instance.
- `ptzsim/onvif.py` — `OnvifCamera`: SOAP over HTTP (Device, Media, PTZ services,
  WS-Security digest auth) and the WS-Discovery responder on UDP 3702. Converts between
  VISCA units and the ONVIF generic spaces (pan/tilt −1…1, zoom 0…1).
- `ptzsim/transports.py` — Sony VISCA over IP (UDP 52381), raw VISCA over TCP/UDP, serial
  via pseudo terminal.
- `ptzsim/ndi.py` — optional NDI source with PTZ control and a rendered test picture.
- `ptzsim/display.py` — live terminal dashboard; `ptzsim/cli.py` — `serve` and `send`.

## What the streaming-server expects (ONVIF)

The server uses `onvif-zeep`: WS-Discovery probe for `dn:NetworkVideoTransmitter`,
then `GetCapabilities`, `Media.GetProfiles` (first profile with a PTZConfiguration),
`ContinuousMove` with `Timeout=PT2S` (resent every 700 ms while a button is held),
`Stop`, `GetStatus` and `AbsoluteMove` (its six presets are stored server-side and
recalled via `AbsoluteMove`). Camera-side `SetPreset`/`GotoPreset` are not used by it.
Keep these calls compatible when changing `onvif.py`.
