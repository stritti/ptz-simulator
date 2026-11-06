<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# PTZ Camera Control Protocols: Technical Reference & Specifications

This document provides a comprehensive technical reference for Pan-Tilt-Zoom (PTZ) camera control protocols, covering legacy serial interfaces, standard network protocols, vendor-specific APIs, and official specification documents.

This is a general protocol reference; not all protocols listed here are
implemented by the simulator. ptzsim implements ONVIF (Core Specification
v26.06, PTZ Service Specification v25.12, Imaging Service Specification
v18.12, WS-Discovery 1.0 (April 2005 revision), WS-Security UsernameToken 1.1,
HTTP digest per RFC 2617), Sony VISCA (command list v2.00, VISCA over IP), Pelco-D
(7-byte frames with checksum: drive, stop and preset commands) and NDI PTZ
metadata (`ntk_ptz_*`); see [supported standards](/guide#supported-standards)
in the guide for the full list with versions and references.

## 1. Protocol Comparison Matrix

| Protocol | Type | Transport / Physical Layer | Default Port / Baud Rate | Multi-Cam Capacity | Framing / Format |
| ----- | ----- | ----- | ----- | ----- | ----- |
| **VISCA Serial** | Industry Standard | RS-232 / RS-422 | 9600 / 38400 Baud | Max 7 (Daisy-Chain) | Hex Bytes (`0x8X ... 0xFF`) |
| **Pelco-D** | Open Standard | RS-485 / RS-422 | 2400 Baud (8N1) | Max 255 Addresses | 7-Byte Hex Packet |
| **Pelco-P** | Legacy Standard | RS-485 | 4800 Baud (8N1) | Max 32 Addresses | 8-Byte Hex Packet |
| **VISCA over IP** | Open IP Standard | UDP | Port `52381` | Unlimited (IP-based) | 8-Byte Header + VISCA Payload |
| **ONVIF (Profile S/T)** | Open Interoperability | IP (HTTP / HTTPS) | Port `80` / `443` | Unlimited (IP-based) | SOAP / XML Web Services |
| **NDI PTZ** | Proprietary (Vizrt) | TCP / UDP (NDI Stream) | Port `5960+` | Unlimited (IP-based) | Embedded XML Metadata |
| **Panasonic AW IP** | Vendor Protocol | UDP / HTTP CGI | Port `50001` / `80` | Unlimited (IP-based) | ASCII / HTTP GET |
| **Axis VAPIX** | Vendor Protocol | HTTP / HTTPS REST | Port `80` / `443` | Unlimited (IP-based) | JSON / HTTP Query |

## 2. Serial Protocol Specifications

### 2.1 Pelco-D

Pelco-D is a widely used 7-byte framing protocol operating over RS-485 differential lines.

* **Baud Rate:** 2400 bps (default), 8 data bits, 1 stop bit, no parity (8N1).
* **Address Range:** 1 to 255 (`0x01` to `0xFF`).
* **Frame Structure (7 Bytes):**

```txt
+---------+---------------+-----------+-----------+--------+--------+----------+
| Byte 1  | Byte 2        | Byte 3    | Byte 4    | Byte 5 | Byte 6 | Byte 7   |
+---------+---------------+-----------+-----------+--------+--------+----------+
| Sync    | Camera Addr   | Command 1 | Command 2 | Data 1 | Data 2 | Checksum |
| (0xFF)  | (0x01 - 0xFF) | (Status)  | (Control) | (Pan)  | (Tilt) | (Mod 256)|
+---------+---------------+-----------+-----------+--------+--------+----------+
```

* **Motion Command Field Bitmasks (Byte 4 - Command 2):**
  * Bit 0: Focus Near (`0x01`) in most implementations; the original Pelco manual marks it as fixed to 0
  * Bit 1: Pan Right
  * Bit 2: Pan Left
  * Bit 3: Tilt Up
  * Bit 4: Tilt Down
  * Bit 5: Zoom Tele
  * Bit 6: Zoom Wide
  * Bit 7: Focus Far

* **Data Fields:**
  * **Data 1 (Pan Speed):** Range `0x00` to `0x3F` (`0xFF` for high-speed turbo mode).
  * **Data 2 (Tilt Speed):** Range `0x00` to `0x3F`.

* **Checksum Calculation:**

  `Checksum = (Byte 2 + Byte 3 + Byte 4 + Byte 5 + Byte 6) mod 256`

* **Example Command Frame (Pan Right, Camera Address 1, Pan Speed `0x20`):**
  `FF 01 00 02 20 00 23`

ptzsim implements the drive, stop-all and preset (set `0x03` / call `0x07` / clear
`0x05`) commands described here and answers executed commands with the ACK frame
`FF <addr> 00 FF 00 00 <checksum>`; see
[Testing Pelco-D clients](/guide#testing-pelco-d-clients) in the guide.

### 2.2 Pelco-P

Pelco-P uses an 8-byte structure bounded by `STX` (`0xA0`) and `ETX` (`0xAF`) delimiters.

* **Baud Rate:** 4800 bps (default), 8N1.
* **Address Range:** 1 to 32 (encoded internally as `0x00` to `0x1F`).
* **Frame Structure (8 Bytes):**

```txt
+------+-----------+---------+---------+-----------+------------+------+----------+
| Byte | 1         | 2       | 3       | 4         | 5          | 6    | 7        |
+------+-----------+---------+---------+-----------+------------+------+----------+
| Field| STX(0xA0) | Address | Data 1  | Data 2    | Pan Speed  | Tilt | ETX(0xAF)|
|      |           | (0-31)  | (Cmd 1) | (Cmd 2)   | (0x00-3F)  | Speed|          |
+------+-----------+---------+---------+-----------+------------+------+----------+
```

* Byte 8: XOR Checksum of Bytes 1 to 7.

### 2.3 VISCA Serial (RS-232 / RS-422)

VISCA (Video System Control Architecture) is a packet-based protocol developed by Sony that relies on a daisy-chain configuration.

* **Baud Rate:** 9600 / 38400 bps, 8N1.
* **Topology:** Up to 7 cameras linked sequentially. Addresses are automatically assigned (`0x01` through `0x07`).
* **Packet Framing:**
  * **Header Byte:** `0x80 | Target Address` (e.g., `0x81` for Camera 1).
  * **Terminator Byte:** Always `0xFF`.

#### Command Format Example: Pan-Tilt Drive

```txt
81 01 06 01 VV WW RR SS FF
```

* `81`: Target Camera 1 (Command from Controller)
* `01 06 01`: Pan-Tilt Drive Category
* `VV`: Pan Speed (`0x01` to `0x18`)
* `WW`: Tilt Speed (`0x01` to `0x14`)
* `RR`: Pan Direction (`0x01` = Left, `0x02` = Right, `0x03` = Stop)
* `SS`: Tilt Direction (`0x01` = Up, `0x02` = Down, `0x03` = Stop)
* `FF`: Message Terminator

#### Response Frames

* **ACK:** `X0 41 FF` (where `X` is Camera Address + 8)
* **Completion:** `X0 51 FF`
* **Error:** `X0 60 02 FF` (Syntax Error)

---

## 3. IP-Based Protocol Specifications

### 3.1 VISCA over IP

VISCA over IP encapsulates standard VISCA payloads inside UDP packets with an added 8-byte header.

* **Transport:** UDP, Default Port `52381`
* **Packet Layout:**

```txt
+-----------------------+--------------------+--------------------------------+-------------------+
| Bytes 0-1             | Bytes 2-3          | Bytes 4-7                      | Bytes 8+          |
+-----------------------+--------------------+--------------------------------+-------------------+
| Payload Type          | Payload Length     | Sequence Number                | Payload           |
| (0x0100 = Command)    | (Length of payload)| (32-bit uint incrementing)     | (Raw VISCA Bytes) |
+-----------------------+--------------------+--------------------------------+-------------------+
```

#### Payload Types

* `0x01 00`: VISCA Command
* `0x01 10`: VISCA Inquiry
* `0x01 11`: VISCA Reply
* `0x01 20`: Device Setting Command

### 3.2 ONVIF PTZ Service (Profile S / Profile T)

ONVIF provides a standardized SOAP/XML interface for controlling IP network cameras over HTTP/HTTPS.

* **Transport:** HTTP / HTTPS on Port `80` / `443`
* **Data Model:** XML Web Services via SOAP envelopes
* **Key WSDL Operations (`PTZService`):**
  * `ContinuousMove`: Controls pan/tilt/zoom speeds using normalized vector values `v` in `[-1.0, 1.0]`.
  * `AbsoluteMove`: Moves PTZ mechanism to precise coordinates `(x, y, z)`.
  * `RelativeMove`: Shifts current position by a relative vector `(delta x, delta y, delta z)`.
  * `Stop`: Halts ongoing pan/tilt/zoom movement.
  * `SetPreset` / `GotoPreset`: Stores and recalls camera presets.

#### Example SOAP Payload (Continuous Move Request)

```xml
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:tt="http://www.onvif.org/ver10/schema">
  <s:Body>
    <ContinuousMove xmlns="http://www.onvif.org/ver20/ptz/wsdl">
      <ProfileToken>Profile_1</ProfileToken>
      <Velocity>
        <tt:PanTilt x="0.4" y="-0.2" space="http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace"/>
        <tt:Zoom x="0.0"/>
      </Velocity>
    </ContinuousMove>
  </s:Body>
</s:Envelope>
```

### 3.3 NDI PTZ (Network Device Interface)

NDI integrates control commands directly within its IP video streaming protocol stack.

* **Transport:** NDI Control Channel (TCP/UDP, Dynamic ports starting at `5960`).
* **Mechanism:** Controls are sent as inline XML metadata over the established NDI connection.
* **Features:** Bidirectional status exchange (Program/Preview Tally), Pan/Tilt/Zoom continuous vector control, and preset synchronization without requiring a dedicated secondary connection.

### 3.4 Vendor REST APIs / CGI Interfaces

#### Panasonic AW Protocol

* **Transport:** UDP Port `50001` or HTTP GET requests on Port `80`.
* **CGI Command Examples:**
  * Absolute Pan/Tilt positioning:
    `GET http://<camera-ip>/cgi-bin/aw_ptz?cmd=%23APS80008000&res=1`
  * Direct Speed Drive:
    `GET http://<camera-ip>/cgi-bin/aw_ptz?cmd=%23PTS5050&res=1`

#### Axis VAPIX API

* **Transport:** HTTP / HTTPS REST requests on Port `80` / `443`.
* **CGI Command Examples:**
  * Move Pan/Tilt continuously:
    `GET /axis-cgi/com/ptz.cgi?continuouspantiltmove=30,-15`
  * Go to absolute position:
    `GET /axis-cgi/com/ptz.cgi?pan=120&tilt=-10&zoom=1500`

---

## 4. Architectural Selection Guide

* **Live Broadcast & Production:** Use **VISCA over IP** for low latency and hardware controller compatibility (e.g., Stream Deck, Sony RM-IP Series). Use **NDI PTZ** when operating in pure NDI workflows.
* **Security & Video Surveillance:** Use **ONVIF (Profile S/T)** for broad compatibility with Video Management Systems (VMS) like Milestone or Genetec.
* **Legacy & Long-Distance Cabling:** Use **Pelco-D** or **VISCA RS-422** when operating over dedicated twisted-pair copper wire setups without Ethernet infrastructure.

---

## 5. Official Specifications & Developer Resources

Below is a curated collection of official technical specifications, developer manuals, and WSDL links for implementation reference.

### 5.1 Serial Protocols

* **Pelco-D Protocol Guide:**
  * [CommFront Pelco-D Tutorial & Specifications](https://www.commfront.com/pages/pelco-d-protocol-tutorial)
* **Pelco-P Protocol Guide:**
  * [CommFront Pelco-P Tutorial & Specifications](https://www.commfront.com/pages/pelco-p-protocol-tutorial)
* **Sony VISCA Command List (RS-232 / RS-422):**
  * [Sony Technical Manual & VISCA Command Reference (PDF)](https://pro.sony/s3/2022/09/03065933/VISCA_Command_List_v4.pdf)

### 5.2 VISCA over IP

* **Sony VISCA over IP Protocol Specification:**
  * Detailed specification included in official Sony PTZ Camera Manuals (e.g., BRC-X400 / SRG-X120 Technical Manuals).
* **Vendor Implementation Guides:**
  * [AVer PTZ Camera VISCA Command Codes](https://communication.aver.com/DownloadFile.aspx?n=5294|A4C91B77-6295-4034-818F-8D7E4D67680A&t=ServiceDownload)
  * [PTZOptics VISCA & Developer Documentation Portal](https://ptzoptics.com/developer-portal/)

### 5.3 ONVIF (Open Network Video Interface Forum)

* **ONVIF PTZ Service Specification:**
  * [ONVIF PTZ Service Specification Document (PDF)](https://www.onvif.org/specs/srv/ptz/ONVIF-PTZ-Service-Spec.pdf)
* **ONVIF WSDL Definitions (For Code Generation):**
  * [ONVIF PTZ Service WSDL File (`ptz.wsdl`)](https://www.onvif.org/ver20/ptz/wsdl/ptz.wsdl)
  * [ONVIF Schema Specifications (`onvif.xsd`)](https://www.onvif.org/ver10/schema/onvif.xsd)
* **ONVIF Profile Specs:**
  * [ONVIF Profile T (Advanced Streaming)](https://www.onvif.org/profiles/profile-t/)
  * [ONVIF Profile S (Basic Streaming)](https://www.onvif.org/profiles/profile-s/)

### 5.4 Broadcast & IP Infrastructure APIs

* **NDI PTZ Development:**
  * [Vizrt NDI SDK & Developer Portal](https://ndi.video/developer/)
* **Panasonic Professional AV IP Control Protocol:**
  * [Panasonic Professional AV Manuals & IP Control Documentation](https://pro-av.panasonic.net/en/manual/)
* **Axis VAPIX Control API:**
  * [Axis Communications VAPIX PTZ API Reference](https://www.axis.com/developer-community/vapix)
