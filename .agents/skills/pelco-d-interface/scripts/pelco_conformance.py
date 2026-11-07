#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Pelco-D conformance smoke test for a camera-side Pelco-D endpoint.

Opens a serial device (e.g. the pty of `ptzsim serve --pelco-d /tmp/ttyPelcoD`),
sends Pelco-D frames and checks the 4-byte general response
`FF <addr> <cmd1> <checksum>` for drive/stop/preset commands, plus the error
behaviour: a wrong checksum and a frame for another address must get NO reply.

Usage:
    python3 pelco_conformance.py --port /tmp/ttyPelcoD --address 1

Exits 0 when every check passes, 1 otherwise. Standard library only, Python 3.8+.
"""

from __future__ import annotations

import argparse
import os
import select
import sys
import termios
import time
import tty

SYNC = 0xFF
CMD2_PAN_RIGHT = 0x02
CMD2_ZOOM_TELE = 0x20
CMD2_SET_PRESET, CMD2_CLEAR_PRESET, CMD2_CALL_PRESET = 0x03, 0x05, 0x07


def frame(addr: int, cmd1: int, cmd2: int, data1: int, data2: int, bad_checksum: bool = False) -> bytes:
    chk = (addr + cmd1 + cmd2 + data1 + data2) & 0xFF
    if bad_checksum:
        chk = (chk + 1) & 0xFF
    return bytes([SYNC, addr, cmd1, cmd2, data1, data2, chk])


def response(sent: bytes) -> bytes:
    """4-byte general response: sync, address, cmd1 echo, request checksum echo."""
    return bytes([SYNC, sent[1], sent[2], sent[-1]])


def dump(data: bytes) -> str:
    return " ".join("%02X" % b for b in data)


class SerialPort:
    def __init__(self, path: str, timeout: float, baud: int = 2400):
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        tty.setraw(self.fd)
        speed = getattr(termios, "B%d" % baud, None)
        if speed is None:
            os.close(self.fd)
            raise ValueError("unsupported baud rate %d" % baud)
        attrs = termios.tcgetattr(self.fd)
        attrs[4] = attrs[5] = speed  # input/output speed
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        termios.tcflush(self.fd, termios.TCIOFLUSH)
        self.timeout = timeout

    def close(self) -> None:
        os.close(self.fd)

    def send(self, data: bytes) -> None:
        os.write(self.fd, data)

    def recv(self, n: int, timeout: float) -> bytes:
        """Read up to n bytes; return b'' on timeout."""
        out = b""
        end = time.monotonic() + timeout
        while len(out) < n and time.monotonic() < end:
            ready, _, _ = select.select([self.fd], [], [], max(0.0, end - time.monotonic()))
            if not ready:
                break
            try:
                chunk = os.read(self.fd, n - len(out))
            except BlockingIOError:
                continue
            if not chunk:
                break
            out += chunk
        return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Pelco-D conformance smoke test")
    parser.add_argument("--port", required=True, help="serial device path (e.g. /tmp/ttyPelcoD)")
    parser.add_argument("--address", type=int, default=1, help="camera address 1..255 (default 1)")
    parser.add_argument("--preset", type=int, default=90, metavar="N",
                        help="preset number 0..99 used for set/call/clear (default 90; "
                             "the preset is cleared again at the end)")
    parser.add_argument("--timeout", type=float, default=2.0, help="reply timeout in seconds")
    parser.add_argument("--baud", type=int, default=2400,
                        help="serial baud rate, applied via termios (default 2400)")
    parser.add_argument("--foreign-address", type=int, default=None, metavar="ADDR",
                        help="address for the foreign-address silence check; must be unused "
                             "on the bus (default: 2 if --address is 1, else 1)")
    args = parser.parse_args()
    if not 1 <= args.address <= 255 or not 0 <= args.preset <= 99:
        parser.error("--address must be 1..255 and --preset 0..99")
    other_address = args.foreign_address or (2 if args.address == 1 else 1)
    if not 1 <= other_address <= 255 or other_address == args.address:
        parser.error("--foreign-address must be 1..255 and differ from --address")

    port = SerialPort(args.port, args.timeout, baud=args.baud)
    results = []

    def check(name, sent, expect_reply=True, timeout=None):
        timeout = args.timeout if timeout is None else timeout
        termios.tcflush(port.fd, termios.TCIOFLUSH)
        port.send(sent)
        got = port.recv(4, timeout)
        # a valid response must be exactly 4 bytes: probe for trailing garbage
        trailing = port.recv(16, 0.3) if expect_reply and got else b""
        if not expect_reply:
            ok = got == b""
            detail = "silence expected, got %s" % (dump(got) or "nothing")
        else:
            want = response(sent)
            ok = got == want and trailing == b""
            detail = "reply %s, expected %s%s" % (
                dump(got) or "nothing", dump(want),
                ", trailing bytes %s" % dump(trailing) if trailing else "")
        results.append((ok, name, detail))
        print("%s %s — %s" % ("PASS" if ok else "FAIL", name, detail))

    a = args.address
    check("drive pan right -> general response", frame(a, 0x00, CMD2_PAN_RIGHT, 0x20, 0x00))
    check("drive zoom tele -> general response", frame(a, 0x00, CMD2_ZOOM_TELE, 0x20, 0x00))
    check("stop all -> general response", frame(a, 0x00, 0x00, 0x00, 0x00))
    check("set preset %d -> general response" % args.preset,
          frame(a, 0x00, CMD2_SET_PRESET, 0x00, args.preset))
    check("call preset %d -> general response" % args.preset,
          frame(a, 0x00, CMD2_CALL_PRESET, 0x00, args.preset), timeout=10.0)
    check("clear preset %d -> general response" % args.preset,
          frame(a, 0x00, CMD2_CLEAR_PRESET, 0x00, args.preset))
    check("wrong checksum -> silence", frame(a, 0x00, CMD2_PAN_RIGHT, 0x20, 0x00, bad_checksum=True),
          expect_reply=False)
    # foreign-address check uses an unknown, non-motion extended opcode (0x7F), so even
    # a real camera at that address on a shared bus is neither moved nor disturbed
    check("frame for other address -> silence", frame(other_address, 0x00, 0x7F, 0x00, 0x00),
          expect_reply=False)

    port.close()
    failed = [r for r in results if not r[0]]
    print("\n%d/%d checks passed" % (len(results) - len(failed), len(results)))
    for _ok, name, detail in failed:
        print("  FAILED %s: %s" % (name, detail))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
