<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# Choosing a PTZ control protocol

Comparison of the common PTZ camera control protocols. The ptzsim reference simulator
implements VISCA (all transports), ONVIF and Pelco-D (since ptzsim 0.4.0); Pelco-P,
Panasonic AW, Axis VAPIX and the vendor CGI protocols are common but *not* simulated.

| Protocol | Type | Transport / physical | Default port / baud | Multi-cam | Framing |
|---|---|---|---|---|---|
| VISCA serial | industry standard (Sony) | RS-232 / RS-422 | 9600 / 38400 baud, 8N1 | max 7 (daisy chain) | hex bytes `0x8X ... 0xFF` |
| Pelco-D | open standard | RS-485 / RS-422 | 2400 baud, 8N1 | max 255 addresses | 7-byte packet + checksum |
| Pelco-P | legacy standard | RS-485 | 4800 baud, 8N1 | max 32 addresses | 8-byte packet, STX/ETX + XOR |
| VISCA over IP | open IP standard (Sony) | UDP | 52381 | unlimited | 8-byte header + VISCA payload |
| ONVIF Profile S/T | open interoperability | HTTP/HTTPS | 80 / 443 | unlimited | SOAP/XML web services + WS-Discovery |
| NDI PTZ | proprietary (Vizrt) | NDI stream | 5960+ | unlimited | XML metadata in the NDI stream |
| Panasonic AW IP | vendor | UDP 50001 / HTTP CGI | 50001 / 80 | unlimited | ASCII / HTTP GET |
| Axis VAPIX | vendor | HTTP REST | 80 / 443 | unlimited | HTTP query / JSON |

## Selection guide

- **Live broadcast & production** (switchers, Stream Deck, Sony RM-IP): VISCA over IP
  for low latency and hardware-controller compatibility; NDI PTZ inside pure NDI
  workflows.
- **Security & video surveillance** (Milestone, Genetec, … VMS): ONVIF Profile S/T —
  the broadest VMS compatibility.
- **Legacy / long-distance cabling** without Ethernet: Pelco-D or VISCA over RS-422.

## Official specifications and developer resources

- Sony VISCA command list (RS-232/RS-422):
  https://pro.sony/s3/2022/09/03065933/VISCA_Command_List_v4.pdf
- Sony ILME-FR7 VISCA command list (different white-balance codes):
  https://pro.sony/s3/2022/09/14131603/VISCA-Command-List-Version-2.00.pdf
- Axis VISCA interface description (classic BRC/EVI-style command set):
  https://www.axis.com/dam/public/70/3d/31/visca-interface-api-description-en-US-266656.pdf
- VISCA over IP: chapter "VISCA over IP" in the Sony PTZ technical manuals
  (e.g. BRC-X400 / SRG-X120).
- ONVIF PTZ Service Specification:
  https://www.onvif.org/specs/srv/ptz/ONVIF-PTZ-Service-Spec.pdf
- ONVIF Core Specification: https://www.onvif.org/specs/2606/ONVIF-Core-Spec-v2606.pdf
- ONVIF WSDL (`ptz.wsdl`) and schema (`onvif.xsd`):
  https://www.onvif.org/ver20/ptz/wsdl/ptz.wsdl · https://www.onvif.org/ver10/schema/onvif.xsd
- ONVIF Profile S / Profile T: https://www.onvif.org/profiles/profile-s/ ·
  https://www.onvif.org/profiles/profile-t/
- Pelco-D / Pelco-P tutorials: https://www.commfront.com/pages/pelco-d-protocol-tutorial ·
  https://www.commfront.com/pages/pelco-p-protocol-tutorial
- NDI SDK & developer portal: https://ndi.video/developer/
- Panasonic AW IP control manuals: https://pro-av.panasonic.net/en/manual/
- Axis VAPIX PTZ API: https://www.axis.com/developer-community/vapix

## Notes

- **VISCA is not one standard**: transport, replies and error codes are common to Sony
  cameras, but the command set differs per model (white-balance codes, speed ranges,
  4- vs 5-digit positions). Check the command list of the target camera.
- ONVIF coordinates are normalised: pan/tilt −1…1, zoom 0…1, velocities −1…1 — convert
  from the camera's native units at the edge.
