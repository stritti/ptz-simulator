---
title: Specification reference
---

<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# Specification reference

These pages map the protocol specifications that ptzsim implements to what the
simulator does. Each requirement is summarised in our own words, together with the
section of the specification it comes from, so that you can check a camera or client
against the original document.

The specifications themselves are **not** reproduced here. Their licences do not
allow it: ONVIF documents may only be passed on unchanged, and the Pelco, Sony, Axis
and Fujifilm documents may not be redistributed at all. Use the official links
below to read the original text.

| Protocol | Page | Specification (version) | Official source |
|---|---|---|---|
| ONVIF Core, Media, PTZ, Imaging | [ONVIF](./onvif) | Core 26.06, Media 24.12, PTZ Service 25.12, Imaging 18.12 | [onvif.org specifications](https://www.onvif.org/profiles/specifications/) |
| VISCA (serial, TCP/UDP, Sony VISCA over IP) | [VISCA](./visca) | Sony VISCA command list v2.00, Axis VISCA interface description | [Sony](https://pro.sony/s3/2022/09/14131603/VISCA-Command-List-Version-2.00.pdf), [Axis](https://www.axis.com/dam/public/70/3d/31/visca-interface-api-description-en-US-266656.pdf) |
| Pelco-D | [Pelco-D](./pelco-d) | Pelco "D" Protocol v5.0.1 (2008), Fujifilm SX400 Pelco-D v1.10.0 | Pelco manual: on request from Pelco (Motorola Solutions); [Fujifilm SX400](https://asset.fujifilm.com/www/tw/files/2026-04/f5bc920c501c1c6a7f321ad8aa5dcb65/pelco-d_protocol_specification_for_sx400_v1.10.0_en.pdf) |
| NDI PTZ | [NDI](./ndi) | NDI "PTZ and Control Messages" | [docs.ndi.video](https://docs.ndi.video/all/developing-with-ndi/ndi-metadata/ptz-and-control-messages) |

## How to read the tables

- **Section** is the section number in the specification named at the top of the page.
- **Requirement** is a short paraphrase, not a quote.
- **ptzsim** says what the simulator does; *deviation* marks a deliberate difference,
  *not simulated* a feature that is accepted but has no effect, and *missing* a gap.

The test suite (`uv run pytest`) checks the behaviour listed here; tests that check a
specific requirement name its section in a comment.
