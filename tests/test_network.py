# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Network utilities for detecting and displaying IP addresses."""

import socket
import sys

import pytest

from ptzsim import display, network
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


def test_get_network_addresses():
    """Test that network addresses can be retrieved."""
    addresses = get_network_addresses(bind_address="0.0.0.0", include_ipv6=False)
    # Should return at least the loopback interface
    assert isinstance(addresses, dict)
    # Should not be empty
    assert len(addresses) > 0


def test_get_resolved_addresses():
    """Test resolving all addresses for 0.0.0.0."""
    addresses = get_resolved_addresses("0.0.0.0")
    assert isinstance(addresses, list)
    # Should have at least localhost or some interface
    assert len(addresses) > 0
    # All should be strings
    assert all(isinstance(addr, str) for addr in addresses)


def test_get_resolved_addresses_specific_ip():
    """Test resolving a specific IP address."""
    addresses = get_resolved_addresses("127.0.0.1")
    assert addresses == ["127.0.0.1"]


def test_format_addresses_for_display():
    """Test formatting addresses for display."""
    ports = {"ONVIF": 8080, "VISCA/TCP": 5678}
    lines = format_addresses_for_display("0.0.0.0", ports)

    assert isinstance(lines, list)
    assert len(lines) > 0
    # Should show availability
    assert any("Available" in line for line in lines)

    # Test with specific address
    lines = format_addresses_for_display("127.0.0.1", ports)
    assert any("127.0.0.1" in line for line in lines)
