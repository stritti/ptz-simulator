# SPDX-License-Identifier: MIT

"""Fault injection, traffic capture and replay (ptzsim/faults.py, `ptzsim serve --latency` ...)."""

import asyncio
import http.client
import json
import random
import socket
import time

import pytest

from ptzsim.cli import main, send_packets
from ptzsim.faults import (FaultConfig, FaultInjector, TrafficCapture, config_from_args,
                           from_args, parse_script, replay)
from ptzsim.testing import assert_no_errors, free_port, moving_axes, serve
from ptzsim.visca import parse_hex

ZOOM_IN = "81 01 04 07 02 FF"
FOCUS_MODE_INQUIRY = "81 09 04 38 FF"


# ------------------------------------------------------------- config
def test_config_validation():
    assert FaultConfig().active() is False
    assert FaultConfig(latency_ms=10).active() is True
    with pytest.raises(ValueError):
        FaultConfig(loss_pct=101)
    with pytest.raises(ValueError):
        FaultConfig(reorder_pct=-1)
    with pytest.raises(ValueError):
        FaultConfig(latency_ms=-5)
    with pytest.raises(ValueError):
        FaultConfig(disconnect_after=-1)


def test_cli_rejects_bad_fault_options():
    with pytest.raises(SystemExit):
        main(["serve", "--loss", "200"])
    with pytest.raises(SystemExit):
        main(["serve", "--latency", "-1"])


def test_from_args_off_by_default():
    from ptzsim.cli import build_parser
    args = build_parser().parse_args(["serve"])
    injector, capture = from_args(args)
    assert injector is None and capture is None
    assert config_from_args(args) == FaultConfig()


# ------------------------------------------------------- injector (unit)
def run_injector(config, messages, seed=1, on_disconnect=None):
    """Send messages through a wrapped sender inside a loop; return (received, injector, elapsed)."""
    async def run():
        injector = FaultInjector(config, rng=random.Random(seed))
        received = []
        send = injector.wrap("test", "peer", received.append, on_disconnect=on_disconnect)
        if not config.active():
            assert send is received.append  # untouched when nothing is configured
        start = time.monotonic()
        for message in messages:
            send(message)
        await asyncio.sleep(0.4)
        return received, injector, time.monotonic() - start

    return asyncio.run(run())


def test_loss_drops_everything_at_100():
    received, injector, _ = run_injector(FaultConfig(loss_pct=100), [b"\x01", b"\x02"])
    assert received == [] and injector.dropped == 2


def test_duplicate_sends_twice_at_100():
    received, injector, _ = run_injector(FaultConfig(duplicate_pct=100), [b"\x01"])
    assert received == [b"\x01", b"\x01"] and injector.duplicated == 1


def test_latency_delays_the_reply():
    received, injector, elapsed = run_injector(FaultConfig(latency_ms=80), [b"\x01"])
    assert received == [b"\x01"]
    assert elapsed >= 0.07  # the sleep(0.4) only ends after the delayed reply


def test_reorder_delays_so_later_messages_overtake():
    received, injector, _ = run_injector(FaultConfig(reorder_pct=100), [b"\x01", b"\x02"], seed=3)
    assert sorted(received) == [b"\x01", b"\x02"]
    assert injector.reordered == 2


def test_disconnect_after_n_calls_the_hook_and_drops_the_rest():
    calls = []
    received, injector, _ = run_injector(FaultConfig(disconnect_after=2), [b"\x01", b"\x02", b"\x03"],
                                         on_disconnect=lambda: calls.append("bye"))
    assert received == [b"\x01", b"\x02"]
    assert calls == ["bye"] and injector.disconnected == 1


def test_disconnect_fires_only_after_the_allowed_replies_were_delivered():
    async def run():
        events = []
        injector = FaultInjector(FaultConfig(disconnect_after=1, latency_ms=20), rng=random.Random(1))
        send = injector.wrap("test", "peer", lambda d: events.append(("tx", d)),
                             on_disconnect=lambda: events.append(("disconnect",)))
        send(b"\x01")  # scheduled at +20 ms
        send(b"\x02")  # must not fire the hook before the first reply left
        await asyncio.sleep(0.2)
        return events, injector

    events, injector = asyncio.run(run())
    assert events == [("tx", b"\x01"), ("disconnect",)]
    assert injector.disconnected == 1


def test_wait_pending_completes_when_replies_are_duplicated():
    async def run():
        injector = FaultInjector(FaultConfig(duplicate_pct=100), rng=random.Random(1))
        received = []
        send = injector.wrap("test", "peer", received.append)
        send(b"\x01")
        await asyncio.wait_for(injector.wait_pending(), timeout=1.0)  # hung before the fix
        return received

    assert asyncio.run(run()) == [b"\x01", b"\x01"]


# ------------------------------------------------- end to end: VISCA
def talk(port, proto, packets, timeout=1.0):
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, send_packets, [parse_hex(p) for p in packets],
                                "127.0.0.1", port, proto, timeout)


def test_sony_loss_100_no_reply():
    async def run():
        async with serve("--sony", str(free_port(socket.SOCK_DGRAM)), "--loss", "100") as ctx:
            replies = await talk(ctx.args.sony, "sony", [FOCUS_MODE_INQUIRY], timeout=0.3)
            return ctx, replies

    ctx, replies = asyncio.run(run())
    assert replies == []
    assert ctx.simulator.faults.dropped >= 1


def test_tcp_latency_delays_the_reply():
    async def run():
        async with serve("--tcp", str(free_port()), "--latency", "80") as ctx:
            start = time.monotonic()
            replies = await talk(ctx.args.tcp, "tcp", [FOCUS_MODE_INQUIRY])
            return ctx, replies, time.monotonic() - start

    ctx, replies, elapsed = asyncio.run(run())
    assert replies == [parse_hex("90 50 02 FF")]  # autofocus on
    assert elapsed >= 0.07
    assert_no_errors(ctx.camera)


def test_tcp_disconnect_after_first_reply():
    async def run():
        async with serve("--tcp", str(free_port()), "--disconnect-after", "1") as ctx:
            replies = await talk(ctx.args.tcp, "tcp", [FOCUS_MODE_INQUIRY, "81 09 06 12 FF"], timeout=0.4)
            await asyncio.sleep(0.1)
            return ctx, replies

    ctx, replies = asyncio.run(run())
    assert replies == [parse_hex("90 50 02 FF")]  # the second reply is cut off
    assert ctx.simulator.faults.disconnected == 1


def test_sony_duplicate_reaches_the_client_twice():
    async def run():
        async with serve("--sony", str(free_port(socket.SOCK_DGRAM)), "--duplicate", "100") as ctx:
            def raw():
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.settimeout(0.5)
                    from ptzsim.transports import SONY_HEADER, SONY_VISCA_INQUIRY
                    packet = parse_hex(FOCUS_MODE_INQUIRY)
                    s.sendto(SONY_HEADER.pack(SONY_VISCA_INQUIRY, len(packet), 7) + packet,
                             ("127.0.0.1", ctx.args.sony))
                    first = s.recv(64)
                    second = s.recv(64)
                    return first, second
            return ctx, await asyncio.get_running_loop().run_in_executor(None, raw)

    ctx, (first, second) = asyncio.run(run())
    assert first == second and first.endswith(parse_hex("90 50 02 FF"))


# ------------------------------------------------- end to end: capture
def read_capture(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_capture_logs_rx_and_tx(tmp_path):
    cap = tmp_path / "traffic.jsonl"

    async def run():
        async with serve("--sony", str(free_port(socket.SOCK_DGRAM)), "--capture", str(cap)) as ctx:
            await talk(ctx.args.sony, "sony", [ZOOM_IN, FOCUS_MODE_INQUIRY], timeout=0.5)
            await asyncio.sleep(0.1)

    asyncio.run(run())
    entries = read_capture(cap)
    rx = [e for e in entries if e["dir"] == "rx"]
    tx = [e for e in entries if e["dir"] == "tx"]
    assert [bytes.fromhex(e["data"]) for e in rx] == [parse_hex(ZOOM_IN), parse_hex(FOCUS_MODE_INQUIRY)]
    assert all(e["transport"] == "Sony VISCA/IP" and e["peer"] for e in entries)
    assert any(bytes.fromhex(e["data"]).endswith(parse_hex("90 50 02 FF")) for e in tx)
    assert all(e["t"] >= 0 for e in entries)


# ------------------------------------------------- end to end: replay
def test_script_replay_drives_the_camera(tmp_path):
    script = tmp_path / "session.txt"
    script.write_text(f"# demo session\n0.00 {ZOOM_IN}\n0.05 {FOCUS_MODE_INQUIRY}\n")

    async def run():
        async with serve("--sony", str(free_port(socket.SOCK_DGRAM)), "--script", str(script),
                         instant=False) as ctx:
            await asyncio.sleep(0.3)
            return ctx

    ctx = asyncio.run(run())
    assert "zoom" in moving_axes(ctx.state)
    assert_no_errors(ctx.camera)


def test_capture_file_can_be_replayed(tmp_path):
    cap = tmp_path / "cap.jsonl"

    async def record():
        async with serve("--sony", str(free_port(socket.SOCK_DGRAM)), "--capture", str(cap),
                         instant=False) as ctx:
            await talk(ctx.args.sony, "sony", [ZOOM_IN], timeout=0.5)
            await asyncio.sleep(0.1)

    asyncio.run(record())
    assert any(e["dir"] == "rx" for e in read_capture(cap))

    async def replay_it():
        async with serve("--sony", str(free_port(socket.SOCK_DGRAM)), "--script", str(cap),
                         instant=False) as ctx:
            await asyncio.sleep(0.3)
            return ctx

    ctx = asyncio.run(replay_it())
    assert "zoom" in moving_axes(ctx.state)


def test_parse_script_formats_and_errors(tmp_path):
    script = tmp_path / "s.txt"
    script.write_text("# comment\n\n0.5 81 09 04 38 FF\n1.25 0x8101040702FF\n")
    assert parse_script(str(script)) == [(0.5, "script", parse_hex(FOCUS_MODE_INQUIRY)),
                                         (1.25, "script", parse_hex(ZOOM_IN))]
    bad = tmp_path / "bad.txt"
    bad.write_text("no timestamp here\n")
    with pytest.raises(ValueError):
        parse_script(str(bad))
    bad.write_text('{"t": 0.1, "dir": "rx", "transport": "Sony VISCA/IP", "data": "81090438ff"}\n'
                   '{"t": 0.2, "dir": "tx", "transport": "Sony VISCA/IP", "data": "9050ff"}\n')
    # only rx is replayed, with its recorded transport
    assert parse_script(str(bad)) == [(0.1, "Sony VISCA/IP", parse_hex(FOCUS_MODE_INQUIRY))]


def test_replay_logs_to_the_capture(tmp_path):
    cap = tmp_path / "replay.jsonl"
    script = tmp_path / "s.txt"
    script.write_text(f"0.00 {FOCUS_MODE_INQUIRY}\n")

    async def run():
        async with serve("--sony", str(free_port(socket.SOCK_DGRAM)), "--capture", str(cap),
                         "--script", str(script)) as ctx:
            await asyncio.sleep(0.2)

    asyncio.run(run())
    entries = read_capture(cap)
    assert [e["dir"] for e in entries] == ["rx", "tx"]
    assert all(e["transport"] == "script" for e in entries)
    assert bytes.fromhex(entries[1]["data"]) == parse_hex("90 50 02 FF")


# ------------------------------------------------- end to end: ONVIF HTTP
SOAP = ('<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:tds="http://www.onvif.org/ver10/device/wsdl">'
        '<s:Body><tds:GetSystemDateAndTime/></s:Body></s:Envelope>')


def post(port, body=SOAP, timeout=2.0):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    conn.request("POST", "/onvif/device_service", body=body.encode() if isinstance(body, str) else body,
                 headers={"Content-Type": "application/soap+xml", "Connection": "close"})
    response = conn.getresponse()
    payload = response.read()
    conn.close()
    return response.status, payload


def test_onvif_http_latency_and_capture(tmp_path):
    cap = tmp_path / "http.jsonl"

    async def run():
        async with serve("--onvif", str(free_port()), "--no-discovery", "--latency", "60",
                         "--capture", str(cap)) as ctx:
            loop = asyncio.get_running_loop()
            start = time.monotonic()
            status, _ = await loop.run_in_executor(None, post, ctx.args.onvif)
            return ctx, status, time.monotonic() - start

    ctx, status, elapsed = asyncio.run(run())
    assert status == 200 and elapsed >= 0.05
    entries = read_capture(cap)
    assert {e["dir"] for e in entries} == {"rx", "tx"}
    assert all(e["transport"] == "ONVIF" for e in entries)
    assert entries[0]["note"] == "POST /onvif/device_service" and entries[1]["note"] == "HTTP 200"
    # the tx entry is written when the reply actually leaves, not when it was built
    assert bytes.fromhex(entries[1]["data"]).startswith(b"HTTP/1.1 200")
    assert entries[1]["t"] - entries[0]["t"] >= 0.04


def test_onvif_http_loss_times_out_and_captures_no_tx(tmp_path):
    cap = tmp_path / "http.jsonl"

    async def run():
        async with serve("--onvif", str(free_port()), "--no-discovery", "--loss", "100",
                         "--capture", str(cap)) as ctx:
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(None, lambda: post(ctx.args.onvif, timeout=0.4))
            except (socket.timeout, TimeoutError):
                pass
            await asyncio.sleep(0.1)

    asyncio.run(run())
    entries = read_capture(cap)
    assert [e["dir"] for e in entries] == ["rx"]  # a dropped reply is never "sent"


ONVIF_MOVE = ('<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
              'xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema">'
              '<s:Body><tptz:ContinuousMove><tptz:ProfileToken>Profile_1</tptz:ProfileToken>'
              '<tptz:Velocity><tt:PanTilt x="0.5" y="0"/></tptz:Velocity></tptz:ContinuousMove>'
              '</s:Body></s:Envelope>')


def test_onvif_capture_can_be_replayed(tmp_path):
    cap = tmp_path / "onvif.jsonl"

    async def record():
        async with serve("--onvif", str(free_port()), "--no-discovery", "--capture", str(cap),
                         instant=False) as ctx:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: post(ctx.args.onvif, body=ONVIF_MOVE))
            await asyncio.sleep(0.1)

    asyncio.run(record())
    entries = read_capture(cap)
    assert any(e["dir"] == "rx" and e["transport"] == "ONVIF" for e in entries)

    async def replay_it():
        async with serve("--onvif", str(free_port()), "--no-discovery", "--script", str(cap),
                         instant=False) as ctx:
            await asyncio.sleep(0.3)
            return ctx

    ctx = asyncio.run(replay_it())
    assert ctx.state.pan_velocity != 0  # the recorded ContinuousMove went through the SOAP handler


def test_script_with_onvif_entries_requires_the_onvif_service(tmp_path):
    cap = tmp_path / "c.jsonl"
    cap.write_text('{"t": 0.0, "dir": "rx", "transport": "ONVIF", "data": "3c783e"}\n')

    async def run():
        async with serve("--sony", str(free_port(socket.SOCK_DGRAM)), "--script", str(cap)):
            pass

    with pytest.raises(ValueError):
        asyncio.run(run())
    with pytest.raises(SystemExit):  # the CLI rejects it at parse time
        main(["serve", "--script", str(cap)])


def test_traffic_capture_writes_jsonl(tmp_path):
    cap = TrafficCapture(str(tmp_path / "c.jsonl"))
    cap.log("rx", "VISCA/TCP", "127.0.0.1:1", parse_hex(ZOOM_IN), note="demo")
    cap.close()
    (entry,) = read_capture(tmp_path / "c.jsonl")
    assert entry["dir"] == "rx" and entry["data"] == parse_hex(ZOOM_IN).hex()
    assert entry["transport"] == "VISCA/TCP" and entry["note"] == "demo"


def test_replay_uses_the_script_timing(tmp_path):
    script = tmp_path / "s.txt"
    script.write_text(f"0.00 {FOCUS_MODE_INQUIRY}\n0.15 {FOCUS_MODE_INQUIRY}\n")

    async def run():
        from ptzsim.transports import Simulator
        from ptzsim.visca import ViscaCamera
        sim = Simulator(ViscaCamera(instant=True))
        seen = []
        orig = sim.process

        def spy(packet, send):
            seen.append(time.monotonic())
            return orig(packet, send)

        sim.process = spy
        task = asyncio.ensure_future(replay(sim, str(script)))
        await asyncio.sleep(0.4)
        task.cancel()
        return seen

    seen = asyncio.run(run())
    assert len(seen) == 2 and 0.1 <= seen[1] - seen[0] <= 0.3
