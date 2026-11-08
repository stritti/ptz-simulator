# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Network utilities for detecting and displaying IP addresses."""

import asyncio
import builtins
import ctypes
from contextlib import suppress
import socket
import sys
import threading

import pytest

from ptzsim import builtin_protocols, cli, display, network
from ptzsim.tui import TuiController
from ptzsim.visca import ViscaCamera
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

    class NoServer:
        def close(self):
            pass

    async def no_tcp_server(sim, host, port):
        return NoServer()

    monkeypatch.setattr(network.socket, "getfqdn", slow_fqdn)
    monkeypatch.setattr(network, "_getifaddrs", lambda: {})
    monkeypatch.setattr(builtin_protocols, "serve_tcp", no_tcp_server)
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


# ------------------------------------------------------- edge cases and fallbacks
def test_interface_info_display_and_ipv6_loopback_filter():
    info = InterfaceInfo("eth0")
    info.add_ipv4("10.0.0.1", "255.255.255.0")
    info.add_ipv4("10.0.0.2")  # without netmask
    info.add_ipv6("fe80::1")
    info.add_ipv6("::1")  # loopback is filtered out
    info.add_ipv6("")
    text = info.format_display()
    assert "  eth0:" in text
    assert "    IPv4: 10.0.0.1" in text and "           Netmask: 255.255.255.0" in text
    assert "    IPv4: 10.0.0.2" in text
    assert "    IPv6: fe80::1" in text
    assert "IPv6: ::1" not in text  # loopback filtered (fe80::1 contains "::1" as substring)


def test_hostname_falls_back_to_unknown_when_the_socket_fails(monkeypatch):
    def fail():
        raise OSError("no hostname")

    monkeypatch.setattr(network.socket, "gethostname", fail)
    assert network.get_hostname_and_fqdn() == ("unknown", "unknown")


def test_getifaddrs_binding_is_none_without_ctypes(monkeypatch):
    network._getifaddrs_binding.cache_clear()
    real_import = builtins.__import__

    def no_ctypes(name, *args, **kwargs):
        if name == "ctypes":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_ctypes)
    assert network._getifaddrs_binding() is None
    network._getifaddrs_binding.cache_clear()


@pytest.mark.skipif(sys.platform.startswith("win"), reason="ctypes binding exists on Unix")
def test_getifaddrs_binding_uses_the_bsd_sockaddr_layout(monkeypatch):
    network._getifaddrs_binding.cache_clear()
    monkeypatch.setattr(sys, "platform", "darwin")
    try:
        assert network._getifaddrs_binding() is not None  # BSD branch of the Sockaddr struct
    finally:
        network._getifaddrs_binding.cache_clear()


def test_getifaddrs_returns_none_without_binding(monkeypatch):
    monkeypatch.setattr(network, "_getifaddrs_binding", lambda: None)
    assert network._getifaddrs() is None


@pytest.mark.skipif(sys.platform.startswith("win"), reason="ctypes binding exists on Unix")
def test_getifaddrs_returns_none_when_the_syscall_fails(monkeypatch):
    ctypes_mod, _, _, Ifaddrs = network._getifaddrs_binding()
    monkeypatch.setattr(network, "_getifaddrs_binding",
                        lambda: (ctypes_mod, lambda arg: -1, lambda head: None, Ifaddrs))
    assert network._getifaddrs() is None


@pytest.mark.skipif(sys.platform.startswith("win"), reason="ctypes binding exists on Unix")
def test_getifaddrs_parses_a_fake_ifaddrs_chain(monkeypatch):
    ctypes_mod, _, _, Ifaddrs = network._getifaddrs_binding()
    SockaddrPtr = Ifaddrs._fields_[3][1]  # POINTER(Sockaddr) type of ifa_addr

    # Same platform split as in network._getifaddrs_binding: Linux uses a 16-bit
    # sa_family, the BSDs/macOS an 8-bit sa_len followed by an 8-bit sa_family.
    # The address stays at offset 4 (IPv4) / 8 (IPv6) in both layouts.
    # c_ubyte arrays: c_char arrays would stop at NUL bytes.
    if sys.platform.startswith("linux"):
        in_fields = [("sa_family", ctypes.c_uint16), ("sin_port", ctypes.c_uint16),
                     ("sin_addr", ctypes.c_ubyte * 4)]
        in6_fields = [("sa_family", ctypes.c_uint16), ("sin6_port", ctypes.c_uint16),
                      ("sin6_flowinfo", ctypes.c_uint32), ("sin6_addr", ctypes.c_ubyte * 16)]
    else:
        in_fields = [("sa_len", ctypes.c_uint8), ("sa_family", ctypes.c_uint8),
                     ("sin_port", ctypes.c_uint16), ("sin_addr", ctypes.c_ubyte * 4)]
        in6_fields = [("sa6_len", ctypes.c_uint8), ("sa_family", ctypes.c_uint8),
                      ("sin6_port", ctypes.c_uint16), ("sin6_flowinfo", ctypes.c_uint32),
                      ("sin6_addr", ctypes.c_ubyte * 16)]

    class SockaddrIn(ctypes.Structure):
        _fields_ = in_fields

    class SockaddrIn6(ctypes.Structure):
        _fields_ = in6_fields

    keep = []

    def make_entry(name, flags, addr_struct, netmask_struct=None, nxt=None):
        entry = Ifaddrs()
        entry.ifa_name = name.encode()
        entry.ifa_flags = flags
        entry.ifa_addr = ctypes_mod.cast(ctypes_mod.byref(addr_struct), SockaddrPtr) if addr_struct else None
        entry.ifa_netmask = (ctypes_mod.cast(ctypes_mod.byref(netmask_struct), SockaddrPtr)
                             if netmask_struct else None)
        entry.ifa_next = (ctypes_mod.cast(ctypes_mod.byref(nxt), ctypes_mod.POINTER(Ifaddrs))
                          if nxt else None)
        keep.extend([entry, addr_struct, netmask_struct, nxt])
        return entry

    def ubytes(data):
        return (ctypes.c_ubyte * len(data))(*data)

    def ipv4(name, flags, addr, netmask=None, nxt=None):
        sa = SockaddrIn()
        sa.sa_family = socket.AF_INET
        sa.sin_addr = ubytes(socket.inet_aton(addr))
        nm = None
        if netmask:
            nm = SockaddrIn()
            nm.sa_family = socket.AF_INET
            nm.sin_addr = ubytes(socket.inet_aton(netmask))
        return make_entry(name, flags, sa, nm, nxt)

    def ipv6(name, flags, addr, nxt=None):
        sa = SockaddrIn6()
        sa.sa_family = socket.AF_INET6
        sa.sin6_addr = ubytes(socket.inet_pton(socket.AF_INET6, addr))
        return make_entry(name, flags, sa, None, nxt)

    up_running = network.IFF_UP | network.IFF_RUNNING
    extra = ipv4("eth8", up_running, "10.0.0.6")  # no netmask
    tail = make_entry("dummy0", network.IFF_UP, None, None, extra)  # no address, not running
    middle = ipv6("wlan0", up_running, "fe80::1", tail)
    head = ipv4("eth9", up_running | network.IFF_LOOPBACK, "10.0.0.5", "255.255.255.0", middle)

    def fake_getifaddrs(arg):
        ptr = ctypes_mod.cast(arg, ctypes_mod.POINTER(ctypes_mod.POINTER(Ifaddrs)))
        ptr[0] = ctypes_mod.cast(ctypes_mod.byref(head), ctypes_mod.POINTER(Ifaddrs))
        return 0

    monkeypatch.setattr(network, "_getifaddrs_binding",
                        lambda: (ctypes_mod, fake_getifaddrs, lambda h: None, Ifaddrs))
    interfaces = network._getifaddrs()
    assert set(interfaces) == {"eth9", "wlan0", "dummy0", "eth8"}
    assert interfaces["eth9"].ipv4_addresses == [("10.0.0.5", "255.255.255.0")]
    assert interfaces["eth9"].up is True and interfaces["eth9"].loopback is True
    assert interfaces["wlan0"].ipv6_addresses == ["fe80::1"]
    assert interfaces["eth8"].ipv4_addresses == [("10.0.0.6", "")]  # netmask missing
    assert interfaces["dummy0"].up is False  # IFF_UP without IFF_RUNNING
    assert not interfaces["dummy0"].ipv4_addresses and not interfaces["dummy0"].ipv6_addresses


def test_get_network_addresses_for_a_specific_bind(monkeypatch):
    lo = make_interface("lo", ipv4=[("127.0.0.1", "255.0.0.0")])
    lo.loopback = True
    eth = make_interface("eth0", ipv4=[("10.0.0.1", "255.255.255.0"), ("10.0.0.2", "255.255.255.0")])
    monkeypatch.setattr(network, "_getifaddrs", lambda: {"lo": lo, "eth0": eth})
    assert network.get_network_addresses("10.0.0.2") == {"eth0": ["10.0.0.2"]}
    assert network.get_network_addresses("0.0.0.0", include_ipv6=False) == {"eth0": ["10.0.0.1", "10.0.0.2"]}


def test_interfaces_fall_back_to_dns_resolution(monkeypatch):
    monkeypatch.setattr(network, "_getifaddrs", lambda: None)
    monkeypatch.setattr(network.socket, "getaddrinfo", lambda host, port: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", 0)),  # duplicate
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::5", 0, 0, 0)),
    ])
    interfaces = network.get_all_interfaces_detailed()
    assert list(interfaces) == ["hostname"]
    iface = interfaces["hostname"]
    assert iface.ipv4_addresses == [("192.168.1.10", "")]
    assert iface.ipv6_addresses == ["2001:db8::5"]


def test_interfaces_fallback_handles_dns_failure(monkeypatch):
    monkeypatch.setattr(network, "_getifaddrs", lambda: None)

    def fail(host, port):
        raise socket.gaierror("no dns")

    monkeypatch.setattr(network.socket, "getaddrinfo", fail)
    assert network.get_all_interfaces_detailed() == {}


def test_network_addresses_fall_back_to_dns(monkeypatch):
    monkeypatch.setattr(network, "_getifaddrs", lambda: None)
    monkeypatch.setattr(network.socket, "getaddrinfo", lambda host, port: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.1.1", 0)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::9", 0, 0, 0)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fe80::1%eth0", 0, 0, 0)),  # scoped: skipped
    ])
    assert network.get_network_addresses("0.0.0.0") == {"hostname": ["10.1.1.1", "2001:db8::9"]}
    assert network.get_network_addresses("0.0.0.0", include_ipv6=False) == {"hostname": ["10.1.1.1"]}


def test_network_addresses_fallback_adds_the_bound_address(monkeypatch):
    monkeypatch.setattr(network, "_getifaddrs", lambda: None)

    def fail(host, port):
        raise socket.gaierror("no dns")

    monkeypatch.setattr(network.socket, "getaddrinfo", fail)
    assert network.get_network_addresses("192.168.0.5", include_ipv6=False) == {"bound": ["192.168.0.5"]}


def test_format_network_summary_prefers_physical_interfaces(monkeypatch):
    monkeypatch.setattr(network, "get_all_interfaces_detailed", lambda: {
        "lo": make_interface("lo", ipv4=[("127.0.0.1", "255.0.0.0")]),
        "docker0": make_interface("docker0", ipv4=[("172.17.0.1", "255.255.0.0")]),
        "eth0": make_interface("eth0", ipv4=[("172.28.67.216", "255.255.240.0"), ("172.28.67.217", "255.255.240.0"),
                                            ("172.28.67.218", "255.255.240.0"), ("172.28.67.219", "255.255.240.0")]),
    })
    summary = network.format_network_summary()
    assert summary == f"{socket.gethostname()} (172.28.67.216, 172.28.67.217, 172.28.67.218)"  # max 3


def test_format_network_summary_falls_back_to_any_ipv4_then_hostname(monkeypatch):
    monkeypatch.setattr(network, "get_all_interfaces_detailed", lambda: {
        "docker0": make_interface("docker0", ipv4=[("172.17.0.1", "255.255.0.0")]),
        "usb0": make_interface("usb0", ipv4=[("10.9.0.1", "255.255.0.0")]),  # not eth/en/wlan/lo/veth/...
    })
    assert network.format_network_summary() == f"{socket.gethostname()} (10.9.0.1)"
    monkeypatch.setattr(network, "get_all_interfaces_detailed", lambda: {})
    assert network.format_network_summary() == socket.gethostname()


def test_format_addresses_for_display_on_all_interfaces(monkeypatch):
    monkeypatch.setattr(network, "get_resolved_addresses", lambda bind: ["10.0.0.9", "10.0.0.10"])
    lines = network.format_addresses_for_display("0.0.0.0", {"sony": 52381, "tcp": 5678})
    assert lines[0] == "  Available on: 10.0.0.9, 10.0.0.10"
    assert lines[1:] == ["  " + "sony".ljust(15) + " → 10.0.0.9:52381",
                         "  " + "tcp".ljust(15) + " → 10.0.0.9:5678"]


def test_format_addresses_for_display_on_a_specific_bind():
    lines = network.format_addresses_for_display("10.0.0.9", {"tcp": 5678})
    assert lines == ["  " + "tcp".ljust(15) + " → 10.0.0.9:5678"]


def test_get_resolved_addresses_for_a_specific_bind():
    assert network.get_resolved_addresses("127.0.0.1") == ["127.0.0.1"]


def test_client_addresses_list_lan_ipv4_before_hostname_and_skip_bridges(monkeypatch):
    interfaces = {
        "docker0": make_interface("docker0", ipv4=[("172.17.0.1", "255.255.0.0")]),
        "wlan0": make_interface("wlan0", ipv4=[("192.168.1.20", "255.255.255.0")], ipv6=["fe80::1"]),
        "eth0": make_interface("eth0", ipv4=[("10.0.0.5", "255.0.0.0")]),
    }
    monkeypatch.setattr(network, "_getifaddrs", lambda: interfaces)
    assert network.client_addresses() == ["10.0.0.5", "192.168.1.20"]
    assert network.format_client_address("laptop") == "10.0.0.5, 192.168.1.20 or laptop"
    monkeypatch.setattr(network.socket, "gethostname", lambda: "laptop")
    monkeypatch.setattr(network.socket, "getfqdn", lambda: "laptop.corp.example")
    lines = network.format_network_info_for_startup().splitlines()
    assert lines[1] == "Address for clients: 10.0.0.5, 192.168.1.20 or laptop"
    assert "Address for clients:" in display.render_network("t", color=False)


def test_client_addresses_fall_back_to_bridges_and_hostname(monkeypatch):
    bridge = {"docker0": make_interface("docker0", ipv4=[("172.17.0.1", "255.255.0.0")])}
    monkeypatch.setattr(network, "_getifaddrs", lambda: bridge)
    assert network.client_addresses() == ["172.17.0.1"]
    monkeypatch.setattr(network, "_getifaddrs", lambda: {})
    assert network.format_client_address("laptop") == "laptop"


def test_client_address_is_the_listening_address_with_host(monkeypatch):
    lan = {"eth0": make_interface("eth0", ipv4=[("10.0.0.5", "255.0.0.0")])}
    monkeypatch.setattr(network, "_getifaddrs", lambda: lan)
    monkeypatch.setattr(network.socket, "gethostname", lambda: "laptop")
    assert network.format_client_address("laptop", "127.0.0.1") == "127.0.0.1"
    assert network.format_network_info_for_startup("127.0.0.1").splitlines()[1] == "Address for clients: 127.0.0.1"
    assert "Address for clients: 127.0.0.1" in display.render_network("t", color=False, bind_address="127.0.0.1")
    tui = TuiController(ViscaCamera(), bind_address="127.0.0.1")
    tui.handle_key("n")
    assert any("Address for clients: 127.0.0.1" in line for line in tui.layout("t", 120, 40)[0])
