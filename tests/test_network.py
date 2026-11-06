# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Network utilities for detecting and displaying IP addresses."""

import asyncio
from contextlib import suppress
import socket
import sys
import threading

import pytest

from ptzsim import cli, display, network
from ptzsim.network import (InterfaceInfo, format_addresses_for_display, get_all_interfaces_detailed,
                            get_network_addresses, get_resolved_addresses)


def make_interface(name, up=True, ipv4=(), ipv6=()):
    info = InterfaceInfo(name)
    info.up = up
    for address, netmask in ipv4:
        info.add_ipv4(address, netmask)
    for address in ipv6:
        info.add_ipv6(address)
    return info


@pytest.fixture(autouse=True)
def clear_dns_caches():
    resolvers = (network.get_hostname_and_fqdn, network._get_all_interfaces_fallback,
                 network._get_network_addresses_fallback)
    for resolver in resolvers:
        getattr(resolver, "cache_clear", lambda: None)()
    yield
    for resolver in resolvers:
        getattr(resolver, "cache_clear", lambda: None)()


@pytest.mark.skipif(sys.platform == "win32" or not hasattr(socket, "if_nameindex"),
                    reason="compares with Unix interface names")
def test_all_system_interfaces_are_detected_without_extra_packages():
    detected = get_all_interfaces_detailed()
    assert {name for _, name in socket.if_nameindex()} <= set(detected)
    loopback = [iface for iface in detected.values()
                if ("127.0.0.1", "255.0.0.0") in iface.ipv4_addresses]
    assert len(loopback) == 1 and loopback[0].up


def test_network_view_lists_every_interface_with_all_addresses(monkeypatch):
    interfaces = {iface.name: iface for iface in (
        make_interface("veth4b0fbf2", ipv6=["fe80::20f0:f7ff:fed3:7c32"]),
        make_interface("lo", ipv4=[("127.0.0.1", "255.0.0.0"), ("10.255.255.254", "255.255.255.255")]),
        make_interface("docker0", up=False, ipv4=[("172.17.0.1", "255.255.0.0")]),
        make_interface("dummy0"),
        make_interface("eth0", ipv4=[("172.28.67.216", "255.255.240.0")],
                       ipv6=["fe80::215:5dff:fe37:1b5b"]),
    )}
    monkeypatch.setattr(display, "get_all_interfaces_detailed", lambda: interfaces)

    lines = display.render_network("t", color=False).splitlines()

    rows = [line.split() for line in lines]
    names = [row[0] for row in rows if row and row[0] in interfaces]
    assert names == ["eth0", "docker0", "lo", "dummy0", "veth4b0fbf2"]
    by_name = {row[0]: row for row in rows if row and row[0] in interfaces}
    assert by_name["eth0"][1:] == ["up", "172.28.67.216/20", "fe80::215:5dff:fe37:1b5b"]
    assert by_name["docker0"][1:] == ["down", "172.17.0.1/16"]
    assert by_name["lo"][1:] == ["up", "127.0.0.1/8"]
    assert rows[rows.index(by_name["lo"]) + 1] == ["10.255.255.254/32"]
    assert by_name["dummy0"][1:] == ["up", "–"]
    assert by_name["veth4b0fbf2"][1:] == ["up", "fe80::20f0:f7ff:fed3:7c32"]


def test_startup_addresses_skip_loopback_interface_and_list_main_interface_first(monkeypatch):
    lo = make_interface("lo", ipv4=[("127.0.0.1", "255.0.0.0"), ("10.255.255.254", "255.255.255.255")])
    lo.loopback = True
    interfaces = {iface.name: iface for iface in (
        make_interface("docker0", ipv4=[("172.17.0.1", "255.255.0.0")]),
        lo,
        make_interface("eth0", ipv4=[("172.28.67.216", "255.255.240.0")],
                       ipv6=["fe80::215:5dff:fe37:1b5b", "2001:db8::5"]),
    )}
    monkeypatch.setattr(network, "_getifaddrs", lambda: interfaces)

    assert get_resolved_addresses("0.0.0.0") == ["172.28.67.216", "172.17.0.1"]
    assert get_network_addresses("0.0.0.0") == {"eth0": ["172.28.67.216", "2001:db8::5"],
                                                "docker0": ["172.17.0.1"]}
    lines = format_addresses_for_display("0.0.0.0", {"visca-tcp": 5678})
    assert lines == ["  Available on: 172.28.67.216, 172.17.0.1",
                     "  visca-tcp       → 172.28.67.216:5678"]


def test_loopback_only_has_no_reachable_addresses(monkeypatch):
    lo = make_interface("lo", ipv4=[("127.0.0.1", "255.0.0.0")])
    lo.loopback = True
    monkeypatch.setattr(network, "_getifaddrs", lambda: {"lo": lo})

    assert get_network_addresses("0.0.0.0", include_ipv6=False) == {}
    assert get_resolved_addresses("0.0.0.0") == []
    assert format_addresses_for_display("0.0.0.0", {"ONVIF": 8080}) == []


def test_get_resolved_addresses_specific_ip():
    """Test resolving a specific IP address."""
    addresses = get_resolved_addresses("127.0.0.1")
    assert addresses == ["127.0.0.1"]


@pytest.mark.parametrize("fallback", [False, True])
def test_network_redraw_does_not_repeat_dns(monkeypatch, fallback):
    lookups = []

    def fqdn():
        lookups.append("fqdn")
        return "camera.example.test"

    def addresses(*args):
        lookups.append("addresses")
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
                 ("192.0.2.10", 0))]

    iface = make_interface("eth0", ipv4=[("192.0.2.10", "255.255.255.0")])
    monkeypatch.setattr(network.socket, "gethostname", lambda: "camera")
    monkeypatch.setattr(network.socket, "getfqdn", fqdn)
    monkeypatch.setattr(network.socket, "getaddrinfo", addresses)
    monkeypatch.setattr(network, "_getifaddrs", lambda: None if fallback else {"eth0": iface})

    assert "camera.example.test" in network.format_network_info_for_startup()
    assert get_resolved_addresses("0.0.0.0") == ["192.0.2.10"]
    for _ in range(3):
        text = display.render_network("test", color=False)
        assert "camera.example.test" in text and "192.0.2.10" in text
        assert "192.0.2.10" in "\n".join(
            format_addresses_for_display("0.0.0.0", {"ONVIF": 8080})
        )
    assert lookups.count("fqdn") == 1
    assert lookups.count("addresses") <= 2


def test_startup_dns_allows_event_loop_progress(monkeypatch):
    entered, progressed, finished = threading.Event(), threading.Event(), threading.Event()
    observed_progress = []

    def slow_fqdn():
        entered.set()
        observed_progress.append(progressed.wait(timeout=2))
        finished.set()
        return "camera.example.test"

    async def no_tcp_server(sim, host, port):
        pass

    monkeypatch.setattr(network.socket, "getfqdn", slow_fqdn)
    monkeypatch.setattr(network, "_getifaddrs", lambda: {})
    monkeypatch.setattr(cli, "serve_tcp", no_tcp_server)
    args = cli.build_parser().parse_args(
        ["serve", "--tcp", "0", "--host", "127.0.0.1", "--no-tui"]
    )

    async def run():
        loop = asyncio.get_running_loop()
        task = asyncio.create_task(cli._serve(args))
        try:
            assert await loop.run_in_executor(None, entered.wait, 3)
            progressed.set()
            assert await loop.run_in_executor(None, finished.wait, 3)
            assert observed_progress == [True]
        finally:
            progressed.set()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    asyncio.run(run())
