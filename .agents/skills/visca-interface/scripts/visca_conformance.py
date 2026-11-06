#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""VISCA conformance smoke test for a camera-side VISCA endpoint.

Sends the standard VISCA inquiries and commands over raw TCP, raw UDP or Sony
VISCA over IP (UDP 52381) and checks that every reply has the framing the VISCA
standard prescribes: inquiries answer `90 50 ... FF`, commands ACK with
`90 4z FF` and complete with `90 5z FF`, errors are `90 60 02 FF` (syntax) or
`90 6z 05 FF` (no socket). On Sony VISCA over IP the sequence number must be
echoed and fresh messages must not get control replies 0F 01 / 0F 02.

Usage:
    python3 visca_conformance.py --host 192.168.1.50 --transport tcp --port 5678
    python3 visca_conformance.py --host 192.168.1.50 --transport sony   # UDP 52381
    python3 visca_conformance.py --host 127.0.0.1 --transport udp --port 1259

The preset checks store and recall one preset (default 90, `--preset N` to choose);
no preset is ever deleted. Exits 0 when every check passes, 1 otherwise.
Standard library only, Python 3.8+.
"""

from __future__ import annotations

import argparse
import re
import socket
import struct
import sys
import time

SONY_HEADER = struct.Struct(">HHI")
SONY_COMMAND, SONY_INQUIRY, SONY_REPLY = 0x0100, 0x0110, 0x0111
SONY_CONTROL_REPLY = 0x0201
DEFAULT_PORTS = {"tcp": 5678, "udp": 1259, "sony": 52381}


def hx(text: str) -> bytes:
    return bytes.fromhex(text.replace(" ", ""))


def dump(data: bytes) -> str:
    return " ".join("%02X" % b for b in data)


def matches(packet: bytes, pattern: str) -> bool:
    """Match a reply against a VISCA pattern, e.g. '90 4z FF' or '90 50 0p FF'.

    Literal hex characters match themselves (so '4z'/'5z' keep the ACK/completion
    discriminator); 'z' matches one socket nibble and any other non-hex pattern
    character matches one arbitrary nibble.
    """
    regex = ""
    for token in pattern.split():
        for ch in token:
            if ch == "z" or ch not in "0123456789ABCDEF":
                regex += "[0-9A-F]"
            else:
                regex += ch
    return re.fullmatch(regex, dump(packet).replace(" ", "")) is not None


class Endpoint:
    """Sends one VISCA payload and collects the VISCA reply payloads."""

    def __init__(self, host: str, port: int, transport: str, timeout: float):
        self.host, self.port, self.transport = host, port, transport
        self.timeout = timeout
        self.sequence = 1
        if transport == "tcp":
            self.sock = socket.create_connection((host, port), timeout=timeout)
        elif transport in ("udp", "sony"):
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        else:
            raise ValueError(transport)
        self.sock.settimeout(timeout)

    def close(self) -> None:
        self.sock.close()

    def _send_raw(self, payload: bytes) -> None:
        if self.transport == "tcp":
            self.sock.sendall(payload)
        else:
            self.sock.sendto(payload, (self.host, self.port))

    def _recv_raw(self) -> bytes:
        if self.transport == "tcp":
            return self.sock.recv(4096)
        return self.sock.recvfrom(4096)[0]

    def exchange(self, payload: bytes, replies: int = 1, timeout: float = None) -> list:
        """Send one payload, return up to `replies` VISCA reply payloads."""
        timeout = self.timeout if timeout is None else timeout
        seq = None
        if self.transport == "sony":
            kind = SONY_INQUIRY if payload[1] == 0x09 else SONY_COMMAND
            seq = self.sequence
            self._send_raw(SONY_HEADER.pack(kind, len(payload), seq) + payload)
            self.sequence += 1
        else:
            self._send_raw(payload)
        out, control_errors, buffer = [], [], bytearray()
        end = time.monotonic() + timeout
        self.sock.settimeout(max(0.05, timeout))
        while len(out) < replies and time.monotonic() < end:
            try:
                data = self._recv_raw()
            except socket.timeout:
                break
            if not data:
                break
            if self.transport == "sony":
                if len(data) < SONY_HEADER.size:
                    continue
                ptype, length, rseq = SONY_HEADER.unpack_from(data)
                if len(data) != SONY_HEADER.size + length:
                    control_errors.append("length %d != %d" % (length, len(data) - SONY_HEADER.size))
                    continue
                if rseq != seq:
                    control_errors.append("sequence %d != %d" % (rseq, seq))
                    continue
                body = data[SONY_HEADER.size:SONY_HEADER.size + length]
                if ptype == SONY_REPLY:
                    out.append(body)
                elif ptype == SONY_CONTROL_REPLY and body[:1] == b"\x0f":
                    control_errors.append(dump(body))
                continue
            buffer.extend(data)
            while len(out) < replies:
                idx = buffer.find(b"\xff")
                if idx < 0:
                    break
                packet = bytes(buffer[:idx + 1])
                del buffer[:idx + 1]
                if len(packet) > 1:
                    out.append(packet)
        if control_errors:
            out.insert(0, b"CONTROL-ERROR " + control_errors[0].encode())
        return out


def main() -> int:
    parser = argparse.ArgumentParser(description="VISCA conformance smoke test")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--transport", choices=sorted(DEFAULT_PORTS), default="tcp")
    parser.add_argument("--timeout", type=float, default=2.0, help="reply timeout in seconds")
    parser.add_argument("--move-timeout", type=float, default=20.0,
                        help="timeout for completions that wait for motion (preset recall)")
    parser.add_argument("--preset", type=int, default=90, metavar="N",
                        help="preset number 0..99 to store/recall (default 90; the script "
                             "overwrites that preset but never deletes presets)")
    args = parser.parse_args()
    if not 0 <= args.preset <= 99:
        parser.error("--preset must be 0..99")
    port = args.port or DEFAULT_PORTS[args.transport]
    print("note: store/recall uses preset %d (pass --preset to choose another unused one)"
          % args.preset)

    ep = Endpoint(args.host, port, args.transport, args.timeout)
    results = []

    def check(name, payload, expect, replies=1, timeout=None):
        got = ep.exchange(hx(payload), replies=replies, timeout=timeout)
        ok, detail = expect(got)
        results.append((ok, name, detail, got))
        print("%s %s%s" % ("PASS" if ok else "FAIL", name, (" — " + detail) if detail else ""))

    def expect_single(pattern):
        def _expect(got):
            if len(got) != 1:
                return False, "expected 1 reply, got %s" % [dump(g) for g in got]
            return matches(got[0], pattern), "reply %s" % dump(got[0])
        return _expect

    def expect_inquiry(min_len):
        def _expect(got):
            if len(got) != 1 or got[0][:2] != b"\x90\x50" or got[0][-1] != 0xFF \
                    or len(got[0]) < min_len:
                return False, "expected `90 50 ... FF` inquiry reply, got %s" % [dump(g) for g in got]
            return True, "reply %s" % dump(got[0])
        return _expect

    def expect_ack_completion():
        def _expect(got):
            if len(got) != 2:
                return False, "expected ACK + completion, got %s" % [dump(g) for g in got]
            ack, completion = got
            socket = ack[1] & 0x0F
            ok = matches(ack, "90 4z FF") and matches(completion, "90 5z FF") \
                and socket in (1, 2) and socket == completion[1] & 0x0F
            return ok, "ACK %s, completion %s" % (dump(ack), dump(completion))
        return _expect

    check("if_clear", "81 01 00 01 FF", expect_single("90 50 FF"))
    check("power inquiry (on or standby)", "81 09 04 00 FF", expect_inquiry(4))
    check("version inquiry", "81 09 00 02 FF", expect_inquiry(7))
    check("pan/tilt position inquiry (8 payload bytes)", "81 09 06 12 FF",
          lambda got: (len(got) == 1 and len(got[0]) == 11 and got[0][:2] == b"\x90\x50"
                       and got[0][-1] == 0xFF, "reply %s" % [dump(g) for g in got]))
    check("zoom inquiry (4 payload bytes)", "81 09 04 47 FF", expect_inquiry(7))
    check("pan/tilt drive stop (ACK + completion)", "81 01 06 01 01 01 03 03 FF",
          expect_ack_completion(), replies=2)
    preset_hex = "%02X" % args.preset
    check("preset set %d (ACK + completion)" % args.preset,
          "81 01 04 3F 01 %s FF" % preset_hex, expect_ack_completion(), replies=2)
    check("preset recall %d (ACK + completion after motion)" % args.preset,
          "81 01 04 3F 02 %s FF" % preset_hex,
          expect_ack_completion(), replies=2, timeout=args.move_timeout)
    check("cancel free socket 1 -> no socket", "81 21 FF", expect_single("90 61 05 FF"))
    check("malformed command -> syntax error", "81 01 06 01 FF", expect_single("90 60 02 FF"))

    ep.close()
    failed = [r for r in results if not r[0]]
    print("\n%d/%d checks passed" % (len(results) - len(failed), len(results)))
    for _ok, name, detail, got in failed:
        print("  FAILED %s: %s (got %s)" % (name, detail, [dump(g) for g in got]))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
