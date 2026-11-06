# ptzsim – command-line PTZ camera simulator

Simulates a PTZ camera controlled via **ONVIF**, **VISCA** and **NDI**, so PTZ
clients can be tested without a real camera. All protocols control the same
camera. The simulator keeps the camera state (pan, tilt, zoom, focus, presets,
power) and shows it live in the terminal.

ONVIF and VISCA need nothing but Python ≥ 3.8 (standard library only). NDI
additionally needs the `ndi` extra (see [NDI](#ndi)). The project is managed
with [uv](https://docs.astral.sh/uv/): `uv sync` creates `.venv` with the dev
dependencies.

## Supported transports

| Option           | Protocol                                             | Default port |
|------------------|------------------------------------------------------|--------------|
| `--onvif [PORT]` | ONVIF (SOAP over HTTP) + WS-Discovery on UDP 3702    | 8080         |
| `--sony [PORT]`  | Sony VISCA over IP (UDP, 8-byte header)              | 52381        |
| `--tcp [PORT]`   | raw VISCA over TCP (e.g. PTZOptics)                  | 5678         |
| `--udp [PORT]`   | raw VISCA over UDP                                   | 1259         |
| `--pty [LINK]`   | serial VISCA via a pseudo terminal (RS-232/422 stand-in) | –        |
| `--ndi`          | NDI source with PTZ control and a test picture       | NDI default (mDNS, TCP 5960+) |

Transports can be combined; they all control the same camera. Without any option
`--sony` is started.

## Running

```bash
cd ptz-simulator
uv run ptzsim serve --onvif --onvif-user admin --onvif-password secret   # ONVIF with authentication
uv run ptzsim serve --onvif --sony       # ONVIF and VISCA at the same time
uv run ptzsim serve                      # Sony VISCA/IP on UDP 52381
uv run ptzsim serve --tcp --sony         # TCP 5678 and UDP 52381
uv run ptzsim serve --pty /tmp/ttyPTZ    # serial port at /tmp/ttyPTZ
uv run --extra ndi ptzsim serve --ndi --name "Camera 1"  # NDI source "HOSTNAME (Camera 1)"
uv run ptzsim serve --view-only          # dashboard without keyboard control
uv run ptzsim serve --no-tui -v          # line log instead of the dashboard
```

Without uv, `python3 -m ptzsim serve ...` works as well (standard library only).

More options: `--onvif-auth both|digest|wsse` (HTTP digest and/or WS-UsernameToken,
default both), `--onvif-no-absolute` (camera without `AbsoluteMove`, presets only via
`SetPreset`/`GotoPreset`), `--address 1..7` (VISCA address), `--instant` (jump to target
positions instead of moving at motor speed), `--host` (bind address). In
dashboard mode, log messages go to `ptzsim.log`.

## Keyboard control (TUI)

In a terminal, `serve` shows the live dashboard and lets you drive the camera
from the keyboard. Your actions show up in the command log as `TUI`, next to the
commands from ONVIF, VISCA or NDI clients, and they change the same camera, so the
camera state is shared with every connected client. ONVIF clients can read the
current position using `GetStatus`.

| Key | Action |
|-----|--------|
| arrows or `W` `A` `S` `D` | pan/tilt while the key is held (stops ~0.35 s after the last key repeat) |
| `+` / `-` | zoom tele / wide while the key is held |
| space | stop all movement |
| `[` / `]` | jog speed down / up (1–8) |
| `h` | home position |
| `1`–`9` | recall preset |
| `P` then `1`–`9` | save the current position as preset |
| `C` then `1`–`9` | clear preset |
| `f` | toggle autofocus |
| `b` | one-push white balance (sets gains to neutral, locks manual) |
| `o` | power on / standby |
| `q` | quit |

Next to the dashboard (or above it in narrow terminals) the TUI shows the
**camera picture** at the current position: the same virtual scene as the NDI test
picture, drawn with text characters. The horizon is at 0° tilt, the ground has a
5° checker pattern, a post with its angle stands every 45° of pan, and a 1° grid
appears when zoomed in. The field of view is 60° at 1× and narrows with the zoom
(3° at 20×); the caption shows pan, tilt and zoom. Moves from any client show up
in the picture as they happen.

The keyboard UI uses `curses` and needs a terminal, so it is not available on
native Windows Python (use WSL) or when stdin/stdout are redirected; `serve` then
falls back to the read-only dashboard.

## Testing ONVIF clients

1. Start the simulator in the same network as the client:
   `uv run ptzsim serve --onvif --onvif-user admin --onvif-password secret --name "Camera 1"`.
   For several cameras, start several instances with their own port and name
   (`--onvif 8081 --name "Camera 2"`); all of them answer WS-Discovery.
2. Search for cameras with an ONVIF client. The simulator answers the
   WS-Discovery probe (`dn:NetworkVideoTransmitter`) with the XAddr
   `http://<ip>:8080/onvif/device_service` and the name in the scope
   `onvif://www.onvif.org/name/<name>`. Alternatively enter the simulator's IP
   and port directly. Use the user and password from above.
3. Use the client to pan, tilt, zoom, save and recall presets. The dashboard shows
   position, motion, presets and the latest commands.

If a client runs in Docker/WSL and multicast discovery fails, enter the
simulator's address directly. Set `--advertise-host <IP>` if the address
advertised by discovery is not reachable by the client. Port 80 (the ONVIF
default) needs root privileges, so 8080 is the default.

## ONVIF scope

- **Device**: `GetCapabilities`, `GetServices`, `GetSystemDateAndTime`, `GetDeviceInformation`
- **Media**: `GetProfiles`/`GetProfile` (one profile `Profile_1` with a PTZ configuration
  including `DefaultContinuousZoomVelocitySpace`), `GetStreamUri` (`--rtsp-uri`)
- **PTZ**: `ContinuousMove` (with `Timeout`, default 5 s; every new call extends it),
  `Stop`, `AbsoluteMove`, `RelativeMove`, `GetStatus`, `GotoHomePosition`, `SetHomePosition`,
  `GetPresets`, `SetPreset`, `GotoPreset`, `RemovePreset`, `GetNodes`, `GetConfigurations`,
  `GetConfigurationOptions`
- **Authentication**: WS-Security UsernameToken with `PasswordDigest` (or `PasswordText`),
  only when `--onvif-user` is set. `GetCapabilities`, `GetServices` and
  `GetSystemDateAndTime` work without login, as on real cameras.
- **Imaging** (white balance only): `GetImagingSettings`, `SetImagingSettings` and `GetOptions`
  for video source `VideoSource_1`, mode `AUTO`/`MANUAL`, gains 0…255/128 (1.0 = VISCA 0x80). Media
  `GetVideoSources` lists `VideoSource_1` (640×360, 25 fps). ONVIF has no
  one-push trigger, so one push is only available via VISCA, NDI and the `b` key.
- Not supported: Events, Media2. These calls return a SOAP fault
  (`ter:ActionNotSupported`); Events are also missing from `GetCapabilities`.

Coordinates use the generic ONVIF spaces: pan −1…1 (≈ ±170°), tilt −1…1
(−1 = −30°, 0 = level, 1 = +90°), zoom 0…1 (1×…20×), velocities −1…1.
VISCA and ONVIF presets are the same. The ONVIF token and the NDI index are the VISCA wire value (0–63); the dashboard and the keys 1–9 show it as 1–64. Recall uses the preset speed setting; ONVIF `GotoPreset` with a `Speed` element overrides it.

## Testing VISCA clients

Start the simulator with `--sony`, `--tcp`, `--udp` or `--pty /tmp/ttyPTZ` and
enter the IP and port in the client (52381 for Sony VISCA/IP, 5678 for
VISCA/TCP), or `/tmp/ttyPTZ` as the serial port.

## NDI

```bash
uv run --extra ndi ptzsim serve --ndi --name "Camera 1"
```

The simulator shows up as the NDI source `HOSTNAME (Camera 1)` and sends a test
picture (640×360, `--ndi-fps`, default 25): a grid with sky, ground, horizon and
red posts every 45° that moves with pan, tilt and zoom. It announces PTZ support
(`<ndi_capabilities ntk_ptz="true" .../>` with pan/tilt, zoom, focus, autofocus, white balance and preset speed; NDI preset indexes 0–99, of which the camera has 64), so NDI Studio Monitor, vMix, OBS
(DistroAV) etc. offer PTZ control.

It executes the NDI PTZ commands that receivers send as metadata:

| Metadata | Effect | Value range (NDI SDK) |
|---|---|---|
| `ntk_ptz_pan_tilt pan tilt` | absolute pan/tilt | −1 left … +1 right, −1 bottom … +1 top |
| `ntk_ptz_pan_tilt_speed pan_speed tilt_speed` | move pan/tilt | +1 = moving left, +1 = moving up |
| `ntk_ptz_zoom zoom` | absolute zoom | 0 = zoomed in … 1 = zoomed out |
| `ntk_ptz_zoom_speed zoom_speed` | move zoom | +1 = inwards, −1 = outwards |
| `ntk_ptz_focus mode="auto"` / `mode="manual" distance` | focus | 0 = infinity … 1 = close |
| `ntk_ptz_focus_speed distance` | move focus | −1 … +1 |
| `ntk_ptz_store_preset index` / `ntk_ptz_recall_preset index speed` | presets | 0…99, speed 0…1 |
| `ntk_ptz_white_balance mode="auto"` / `mode="one_shot"` / `mode="manual" red blue` | white balance | 0…1 for red/blue, 0.5 neutral; `indoor`/`outdoor` fixed modes |
| `ntk_ptz_exposure`, `ntk_ptz_iris` | accepted and logged, not simulated | – |

NDI presets are the same as for VISCA and ONVIF. `ndi-python` ships the NDI
runtime, which is subject to the NDI license terms (NDI® is a trademark of Vizrt
NDI AB). On Linux, NDI discovery uses mDNS. If a receiver does not find the
source, add the simulator's IP as an extra source or in NDI Access Manager.

## Sending commands by hand

```bash
uv run ptzsim send "81 01 06 04 FF"                    # home (Sony VISCA/IP)
uv run ptzsim send --proto tcp "81 01 04 3F 01 05 FF"  # store preset 5
uv run ptzsim send "81 09 06 12 FF"                    # query position
```

## Supported VISCA commands

VISCA commands follow `docs/visca-interface-api-description-en-US-266656.pdf` (AXIS example). The Sony list in `docs/VISCA-Command-List-Version-2.00.pdf` uses other white balance codes (`04` = ATW).

Commands (reply: ACK `90 41 FF` + completion `90 51 FF`; for absolute moves the
completion is sent once the position has been reached):

| Command | Bytes |
|---|---|
| Power on / standby | `8x 01 04 00 02/03 FF` |
| Zoom stop / tele / wide / variable | `8x 01 04 07 00/02/03/2p/3p FF` |
| Zoom direct | `8x 01 04 47 0p 0q 0r 0s FF` |
| Focus stop / far / near / variable | `8x 01 04 08 00/02/03/2p/3p FF` |
| Focus direct | `8x 01 04 48 0p 0q 0r 0s FF` |
| Auto focus / manual / toggle | `8x 01 04 38 02/03/10 FF` |
| One push AF | `8x 01 04 18 01 FF` |
| White balance mode (00 auto, 01 indoor, 02 outdoor, 04 auto outdoor, 05 manual) | `8x 01 04 35 0p FF` |
| Red / blue gain, relative and absolute | `8x 01 04 03/04 0p FF`, `8x 01 04 43/44 00 00 0p 0q FF` |
| One push white balance | `8x 01 04 10 05 FF` |
| Preset reset / set / recall (pp 00–63, shown as 1–64) | `8x 01 04 3F 00/01/02 pp FF` |
| Preset speed select (1 separate, 2 common) | `8x 01 7E 04 1B 0p FF` |
| Common preset speed (01–32 hex) | `8x 01 7E 04 1C 0p 0p FF` |
| Separate preset speed (01–32 hex) | `8x 01 7E 01 0B pp qq FF` |
| Pan/tilt drive (up, down, left, right, diagonal, stop) | `8x 01 06 01 VV WW XX YY FF` |
| Pan/tilt absolute / relative | `8x 01 06 02/03 VV WW 0Y0Y0Y0Y 0Z0Z0Z0Z FF` |
| Home / reset | `8x 01 06 04 FF` / `8x 01 06 05 FF` |
| Command cancel | `8x 2z FF` (z = socket) |
| IF_Clear | `8x 01 00 01 FF`, `88 01 00 01 FF` |
| Address set | `88 30 01 FF` |

Inquiries (reply `90 50 ... FF`): power `09 04 00`, zoom `09 04 47`,
focus `09 04 48`, focus mode `09 04 38`, white balance mode `09 04 35`, preset speed `09 7E 04 1B`, `09 7E 04 1C`, `09 7E 01 0B`,
pan/tilt position `09 06 12`, max speed `09 06 11`,
pan/tilt status `09 06 10`, version `09 00 02`.

Errors: syntax error `90 60 02 FF`, not executable `90 61 41 FF` (e.g. standby
or preset not set). `IF_Clear` answers `90 50 FF` without ACK. Pan/tilt status
reports "initialization completes" (`20 00`) plus "operating" (`04 00`) or
"operations complete" (`08 00`) and the end-stop bits. In absolute/relative moves
tilt speed `00` means "same as pan", and both 4- and 5-digit coordinates are
accepted (classic BRC/EVI/Axis and newer Sony models).

Sony VISCA/IP (per the Sony VISCA command list, chapter VISCA over IP): the control
command `RESET` (`02 00`) is acknowledged with `02 01 ... 01` and resets the
sequence number; replies carry the sequence number of the request. A repeated
sequence number is not executed again and answered with control reply `0F 01`, a
payload type that does not match the packet (inquiry sent as command or vice versa)
with `0F 02`. The camera address is fixed to 1 over IP: any address is accepted and
replies always come from `90`.

**VISCA is not one standard.** The transport (VISCA over IP, replies, error codes,
sockets) is common to Sony cameras, the command set differs per model. The simulator
follows the classic 4-digit Sony BRC/EVI and Axis command set; check the command
list of the target camera before relying on model-specific commands (e.g. white
balance codes, speed ranges, 5-digit positions on newer Sony models). Simplification:
only one command socket, so "command buffer full" never occurs.

Value ranges: pan −2448…2448 (≈ ±170°), tilt −432…1296 (≈ −30…+90°),
zoom 0x0000…0x4000 (1×…20×), focus 0x1000…0xF000, pan speed 1…0x18,
tilt speed 1…0x17, presets 0…63 (shown as 1…64).

## Tests

```bash
uv run pytest
```

The tests check VISCA, ONVIF and NDI directly and run end to end over real
TCP/UDP sockets, Sony VISCA/IP, HTTP, WS-Discovery and a pseudo terminal. With
`uv run --extra ndi pytest`, a real NDI round trip runs as well (a receiver calls
`NDIlib_recv_ptz_*`, the simulator executes the commands).

There is also a test against the real ONVIF client library
(`onvif-zeep-async`, same WSDLs as `onvif-zeep`):

```bash
PTZSIM_ONVIF_CLIENT=1 uv run --group onvif-client pytest
```

## ONVIF conformance

Checked against the ONVIF Core Specification 26.06 (`docs/ONVIF-Core-Specification.pdf`).
The PTZ Service Specification is not in `docs/`, so the PTZ fault subcodes are not
verified against it. Responses are not validated against the XSD schemas automatically.

- PTZ service: all mandatory operations (GetNodes, GetNode, GetConfigurations,
  GetConfiguration, GetConfigurationOptions, SetConfiguration, ContinuousMove, Stop,
  GetStatus, GetServiceCapabilities), presets, home position, AbsoluteMove and
  RelativeMove. Faults use the spec's chains, e.g. `env:Sender / ter:InvalidArgVal /
  ter:NoProfile`; out-of-range velocity, timeout or position is rejected, SetPreset
  fails while the camera moves (`ter:MovingPTZ`). An omitted axis in ContinuousMove
  keeps moving, a zero velocity stops it.
- Authentication: HTTP digest (RFC 2617, answers 401 with a challenge) and
  WS-UsernameToken with nonce and timestamp; `--onvif-auth` limits it to one of them.
  GetSystemDateAndTime, GetCapabilities, GetServices and GetServiceCapabilities work
  without credentials.
- WS-Discovery: Types `dn:NetworkVideoTransmitter tds:Device`, AppSequence, Hello on
  start and Bye on exit, Probe matching by type and scope (rfc3986/strcmp0), Resolve.

SetConfiguration returns success for the known configuration token but changes nothing.

Not simulated: device management beyond what PTZ clients need (network, users,
scopes, firmware), events, imaging beyond white balance, Media2, preset tours, auxiliary commands, HTTPS.

## Unsupported protocols

These PTZ protocols are common but **not supported** by the simulator:

| Protocol | Used for | Note |
|---|---|---|
| Pelco-D / Pelco-P | serial control over RS-485/RS-422, mostly older surveillance cameras | byte protocol with checksum, about as simple as VISCA |
| Panasonic AW protocol (HTTP CGI) | Panasonic PTZ (AW-UE/AW-HE), supported by many switchers | HTTP GET on `/cgi-bin/aw_ptz` and `/cgi-bin/aw_cam` |
| PTZOptics HTTP-CGI | PTZOptics cameras via browser URL | `/cgi-bin/ptzctrl.cgi`; VISCA over TCP/UDP is supported |
| Sony CGI | Sony BRC/SRG via HTTP | Sony VISCA over IP is supported |
| Axis VAPIX | Axis cameras via HTTP | `/axis-cgi/com/ptz.cgi` |
| Canon XC Protocol | Canon CR-N/CR-X PTZ | no public specification found |
| ONVIF Events, Media2 | ONVIF services besides PTZ | return `ter:ActionNotSupported` |

## References

**ONVIF**
- ONVIF PTZ Service Specification 25.12: https://www.onvif.org/specs/2512/ONVIF-PTZ-Service-Spec-v2512.pdf
- ONVIF Core Specification (device service, WS-Discovery on 239.255.255.250:3702): https://www.onvif.org/specs/2606/ONVIF-Core-Spec-v2606.pdf
- OASIS WS-Security UsernameToken Profile (PasswordDigest = Base64(SHA-1(nonce + created + password))): https://docs.oasis-open.org/wss/v1.1/wss-v1.1-spec-pr-UsernameTokenProfile-01.htm
- ONVIF Imaging Service Specification 18.12 (`docs/ONVIF-Imaging-Service-Spec-v1812.pdf`)
- Client library used for the interop test, onvif-zeep-async: https://pypi.org/project/onvif-zeep-async/

**VISCA**
- Sony BRC-X400/SRG-X400 Technical Manual (VISCA over IP, command list): https://sony.net/Products/CameraSystem/CA/BRC_X400_SRG_X400/Technical_Document/E042100011.pdf
- Sony BRC-X1000/BRC-H800 Command List: https://sony.net/Products/CameraSystem/CA/BRC_X1000_BRC_H800/Technical_Document/C456100111.pdf
- PTZOptics Developer Portal (VISCA over TCP 5678 / UDP 1259, HTTP-CGI): https://ptzoptics.com/developer-portal/
- PTZOptics: introduction to IP control: https://docs.ptzoptics.com/articles/miscellaneous/misc-cameras/an-introduction-to-ip-control-&-scripting-for-ptzoptics-cameras

**NDI**
- NDI docs, "PTZ and Control Messages": https://docs.ndi.video/all/developing-with-ndi/ndi-metadata/ptz-and-control-messages
- NDI SDK, header `Processing.NDI.Recv.ex.h` (value ranges of the `NDIlib_recv_ptz_*` functions), included in the SDK: https://ndi.video/
- ndi-python (Python bindings including the NDI runtime): https://pypi.org/project/ndi-python/

**Unsupported protocols**
- Pelco-D specification (Fujifilm SX400): https://asset.fujifilm.com/www/tw/files/2026-04/f5bc920c501c1c6a7f321ad8aa5dcb65/pelco-d_protocol_specification_for_sx400_v1.10.0_en.pdf
- Pelco-P specification (Fujifilm SX1600): https://asset.fujifilm.com/www/au/files/2023-06/84c9b575b79de420436e8c0d0fa147f8/pelco-p_protocol_specification_for_sx1600_v.1.00.0_en.pdf
- Panasonic AW-UE150/AW-HE145 Interface Specification: https://eww.pass.panasonic.co.jp/pro-av/support/content/guide/DEF/UE150/AW-UE150HE145_InterfaceSpecification_E.pdf
- Sony BRC-X400 CGI Command List: https://shop.ccisolutions.com/StoreFront/jsp/pdf/SON-BRCX400W_cgiCommandList.pdf
- Axis VAPIX Pan/Tilt/Zoom API: https://developer.axis.com/vapix/network-video/pantiltzoom-api/
- Canon CR-N300 specifications (lists the XC Protocol): https://www.canon.co.uk/ptz-cameras/cr-n300/specifications/

## Documentation website

The VitePress site in `website/` uses this README as its guide. Before publishing
it, review the examples for machine-specific hostnames and network addresses.

Node.js 20.19+ (20.x) or 22.12+ is required. From the repository directory:

```bash
cd website
npm ci
npm run docs:dev      # local development server
npm test              # check root and GitHub Pages subpath builds
npm run docs:build    # production build
npm run docs:preview  # preview the production build
```

For a local preview under a project subpath, set the same base path when building
and previewing:

```bash
BASE_PATH=/ptz-simulator npm run docs:build
BASE_PATH=/ptz-simulator npm run docs:preview
```

To publish on GitHub Pages, select **GitHub Actions** under **Settings > Pages >
Build and deployment > Source** in the repository. The `Deploy documentation`
workflow runs on pushes to `main` and can also be started manually. It gets the
site's base path from GitHub Pages, so project sites and root domains both work.

VitePress 1.x depends on an older Vite with development-server security
advisories. The website overrides it with a patched Vite 6 release; VitePress
data and path loaders are not used because they are not fully compatible with
that override. See the [upstream compatibility guidance](https://github.com/vuejs/vitepress/issues/4494).
