# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Client-side helpers in ptzsim.testing, driven over real sockets."""

import asyncio
import socket
import urllib.request

import pytest

from ptzsim.testing import assert_no_errors, assert_stopped, free_port, moving_axes, rejected, serve
from ptzsim.transports import SONY_CONTROL_REPLY, SONY_HEADER, SONY_VISCA_COMMAND, SONY_VISCA_REPLY
from ptzsim.visca import parse_hex

SOAP = ('<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema">'
        '<s:Body>{}</s:Body></s:Envelope>')


def continuous_move(velocity):
    return ('<tptz:ContinuousMove><tptz:ProfileToken>Profile_1</tptz:ProfileToken>'
            f'<tptz:Velocity>{velocity}</tptz:Velocity></tptz:ContinuousMove>')


def soap(port, body):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/onvif/ptz_service", SOAP.format(body).encode(),
        {"Content-Type": "application/soap+xml"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.read()


def visca_ip(port, messages):
    """Send (sequence, hex packet) pairs over Sony VISCA over IP; return every reply."""
    replies = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(0.3)
        for sequence, packet in messages:
            data = parse_hex(packet)
            s.sendto(SONY_HEADER.pack(SONY_VISCA_COMMAND, len(data), sequence) + data, ("127.0.0.1", port))
            while True:
                try:
                    reply = s.recv(1024)
                except socket.timeout:
                    break
                replies.append((SONY_HEADER.unpack_from(reply), reply[SONY_HEADER.size:]))
    return replies


def test_omitted_onvif_axis_keeps_moving_and_assert_stopped_names_it():
    async def run():
        port = free_port()
        async with serve("--onvif", str(port), "--no-discovery") as ctx:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, soap, port, continuous_move(
                '<tt:PanTilt x="0" y="0"/><tt:Zoom x="0.5"/>'))
            # pitfall: switch to pan and leave zoom out instead of sending zoom 0
            await loop.run_in_executor(None, soap, port, continuous_move('<tt:PanTilt x="0.5" y="0"/>'))
            still = moving_axes(ctx.camera.state)
            with pytest.raises(AssertionError, match="zoom"):
                assert_stopped(ctx.camera.state, ["zoom"])
            # correct client: every axis in every ContinuousMove
            await loop.run_in_executor(None, soap, port, continuous_move(
                '<tt:PanTilt x="0" y="0"/><tt:Zoom x="0"/>'))
            assert_stopped(ctx.camera.state)
            assert_no_errors(ctx.camera)
        return still

    assert asyncio.run(run()) == ["pan", "zoom"]


def test_visca_ip_client_pitfalls_are_reported():
    async def run():
        port = free_port(socket.SOCK_DGRAM)
        async with serve("--sony", str(port)) as ctx:
            loop = asyncio.get_running_loop()
            replies = await loop.run_in_executor(None, visca_ip, port, [
                (1, "81 01 06 01 18 17 03 01 FF"),  # tilt up at the spec maximums: fine
                (2, "81 01 06 01 18 18 03 01 FF"),  # tilt speed 0x18: syntax error
                (3, "81 01 06 01 01 01 03 03 FF"),  # stop
                (3, "81 01 06 04 FF"),              # repeated sequence number: 0F 01
            ])
            assert_stopped(ctx.camera.state)
            errors = [e.description for e in rejected(ctx.camera)]
            with pytest.raises(AssertionError, match="control error 0F 01"):
                assert_no_errors(ctx.camera)
        return replies, errors

    replies, errors = asyncio.run(run())
    assert ((SONY_VISCA_REPLY, 4, 2), parse_hex("90 60 02 FF")) in replies
    # the repeated sequence gets only the control reply: no ACK, no completion
    assert [r for r in replies if r[0][2] == 3][-1] == ((SONY_CONTROL_REPLY, 2, 3), b"\x0f\x01")
    assert len([r for r in replies if r[0][2] == 3]) == 3  # ACK + completion of the stop, then 0F 01
    assert len(errors) == 2 and errors[1].startswith("control error 0F 01: repeated sequence number 3")
