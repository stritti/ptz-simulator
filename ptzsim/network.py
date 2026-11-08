# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Network utilities to detect and display available network interfaces and addresses."""

from __future__ import annotations

import functools
import ipaddress
import socket
import sys
from typing import Dict, List, Optional, Tuple

IFF_UP, IFF_LOOPBACK, IFF_RUNNING = 0x1, 0x8, 0x40  # same values on Linux, macOS and the BSDs


class InterfaceInfo:
    """Information about a single network interface."""

    def __init__(self, name: str):
        self.name = name
        self.ipv4_addresses: List[Tuple[str, str]] = []  # (address, netmask)
        self.ipv6_addresses: List[str] = []  # addresses without scope
        self.up: Optional[bool] = None  # None when the state is unknown
        self.loopback = False

    def add_ipv4(self, address: str, netmask: str = "") -> None:
        """Add an IPv4 address and optional netmask."""
        self.ipv4_addresses.append((address, netmask))

    def add_ipv6(self, address: str) -> None:
        """Add an IPv6 address (scope stripped)."""
        if address and not address.startswith("::1"):
            self.ipv6_addresses.append(address)

    def format_display(self) -> str:
        """Format as a display string."""
        parts = [f"  {self.name}:"]
        for addr, netmask in self.ipv4_addresses:
            parts.append(f"    IPv4: {addr}")
            if netmask:
                parts.append(f"           Netmask: {netmask}")
        for addr in self.ipv6_addresses:
            parts.append(f"    IPv6: {addr}")
        return "\n".join(parts)


@functools.lru_cache(maxsize=1)
def get_hostname_and_fqdn() -> Tuple[str, str]:
    """Resolve the hostname and fully qualified domain name once per process."""
    try:
        hostname = socket.gethostname()
        fqdn = socket.getfqdn()
        return hostname, fqdn
    except Exception:
        return "unknown", "unknown"


def get_all_interfaces_detailed() -> Dict[str, InterfaceInfo]:
    """
    Get detailed information about all network interfaces.

    Returns a dictionary mapping interface names to InterfaceInfo objects, including
    interfaces without an IP address. Uses getifaddrs(3) from the C library (Linux,
    macOS, BSD) and falls back to resolving the hostname where it is unavailable.
    """
    interfaces = _getifaddrs()
    return interfaces if interfaces is not None else _get_all_interfaces_fallback()


@functools.lru_cache(maxsize=None)
def _getifaddrs_binding():
    """ctypes binding of getifaddrs(3), or None (Windows, Python without ctypes)."""
    try:
        import ctypes

        libc = ctypes.CDLL(None)
        getifaddrs, freeifaddrs = libc.getifaddrs, libc.freeifaddrs
    except (ImportError, OSError, TypeError, AttributeError):
        return None

    class Sockaddr(ctypes.Structure):
        if sys.platform.startswith("linux"):
            _fields_ = [("sa_family", ctypes.c_uint16)]
        else:  # BSD layout, also used by macOS
            _fields_ = [("sa_len", ctypes.c_uint8), ("sa_family", ctypes.c_uint8)]

    class Ifaddrs(ctypes.Structure):
        pass

    Ifaddrs._fields_ = [
        ("ifa_next", ctypes.POINTER(Ifaddrs)),
        ("ifa_name", ctypes.c_char_p),
        ("ifa_flags", ctypes.c_uint),
        ("ifa_addr", ctypes.POINTER(Sockaddr)),
        ("ifa_netmask", ctypes.POINTER(Sockaddr)),
        ("ifa_dstaddr", ctypes.c_void_p),
        ("ifa_data", ctypes.c_void_p),
    ]
    getifaddrs.argtypes = [ctypes.POINTER(ctypes.POINTER(Ifaddrs))]
    getifaddrs.restype = ctypes.c_int
    freeifaddrs.argtypes = [ctypes.POINTER(Ifaddrs)]
    freeifaddrs.restype = None
    return ctypes, getifaddrs, freeifaddrs, Ifaddrs


def _getifaddrs() -> Optional[Dict[str, InterfaceInfo]]:
    binding = _getifaddrs_binding()
    if binding is None:
        return None
    ctypes, getifaddrs, freeifaddrs, Ifaddrs = binding

    def address(sockaddr, family: int) -> str:
        # sin_addr is at offset 4 in sockaddr_in, sin6_addr at offset 8 in sockaddr_in6.
        offset, size = (4, 4) if family == socket.AF_INET else (8, 16)
        start = ctypes.cast(sockaddr, ctypes.c_void_p).value + offset
        return socket.inet_ntop(family, ctypes.string_at(start, size))

    head = ctypes.POINTER(Ifaddrs)()
    if getifaddrs(ctypes.byref(head)) != 0:
        return None
    interfaces: Dict[str, InterfaceInfo] = {}
    try:
        entry = head
        while entry:
            ifa = entry.contents
            name = ifa.ifa_name.decode(errors="replace")
            info = interfaces.setdefault(name, InterfaceInfo(name))
            info.up = ifa.ifa_flags & (IFF_UP | IFF_RUNNING) == IFF_UP | IFF_RUNNING
            info.loopback = bool(ifa.ifa_flags & IFF_LOOPBACK)
            family = ifa.ifa_addr.contents.sa_family if ifa.ifa_addr else None
            if family == socket.AF_INET:
                netmask = address(ifa.ifa_netmask, family) if ifa.ifa_netmask else ""
                info.add_ipv4(address(ifa.ifa_addr, family), netmask)
            elif family == socket.AF_INET6:
                info.add_ipv6(address(ifa.ifa_addr, family))
            entry = ifa.ifa_next
    finally:
        freeifaddrs(head)
    return interfaces


def interface_sort_key(iface: InterfaceInfo) -> tuple:
    """Physical interfaces first, then other interfaces with IPv4, loopback, the rest."""
    if iface.name.startswith(("eth", "en", "wl")):
        group = 0
    elif iface.loopback or iface.name.startswith("lo"):
        group = 2
    elif iface.name.startswith("veth") or not (iface.ipv4_addresses or iface.ipv6_addresses):
        group = 3
    else:
        group = 1
    return group, iface.name


def get_network_addresses(
    bind_address: str = "0.0.0.0",
    include_ipv6: bool = True,
) -> Dict[str, List[str]]:
    """
    Get all available IP addresses for network interfaces.

    Returns a dictionary mapping interface names to lists of IP addresses, main
    interfaces first. If bind_address is "0.0.0.0", returns the addresses reachable
    from other hosts (no loopback, no link-local IPv6).
    """
    interfaces = _getifaddrs()
    if interfaces is None:
        return _get_network_addresses_fallback(bind_address, include_ipv6)

    addresses: Dict[str, List[str]] = {}
    for iface in sorted(interfaces.values(), key=interface_sort_key):
        iface_addrs = [addr for addr, _ in iface.ipv4_addresses]
        if include_ipv6:
            iface_addrs += iface.ipv6_addresses
        if bind_address == "0.0.0.0":
            if iface.loopback:
                continue
            iface_addrs = [addr for addr in iface_addrs if not ipaddress.ip_address(addr).is_loopback
                           and not ipaddress.ip_address(addr).is_link_local]
        else:
            iface_addrs = [addr for addr in iface_addrs if addr == bind_address]
        if iface_addrs:
            addresses[iface.name] = iface_addrs
    return addresses



@functools.lru_cache(maxsize=1)
def _get_all_interfaces_fallback() -> Dict[str, InterfaceInfo]:
    """Startup DNS snapshot when getifaddrs is unavailable."""
    interfaces_info: Dict[str, InterfaceInfo] = {}
    hostname = socket.gethostname()

    try:
        addr_info = socket.getaddrinfo(hostname, None)
        main_iface = InterfaceInfo("hostname-resolution")

        seen_addrs = set()
        for family, socktype, proto, canonname, sockaddr in addr_info:
            addr = sockaddr[0]
            if addr not in seen_addrs:
                seen_addrs.add(addr)
                if family == socket.AF_INET:
                    main_iface.add_ipv4(addr)
                elif family == socket.AF_INET6:
                    main_iface.add_ipv6(addr)

        if main_iface.ipv4_addresses or main_iface.ipv6_addresses:
            interfaces_info["hostname"] = main_iface
    except Exception:
        pass

    return interfaces_info


@functools.lru_cache(maxsize=None)
def _get_network_addresses_fallback(
    bind_address: str = "0.0.0.0",
    include_ipv6: bool = True,
) -> Dict[str, List[str]]:
    """Startup DNS snapshot of reachable addresses when getifaddrs is unavailable."""
    addresses: Dict[str, List[str]] = {}

    try:
        # Try to get the hostname and resolve it
        hostname = socket.gethostname()

        # Get all addresses for this hostname
        try:
            addr_info = socket.getaddrinfo(hostname, None)
            unique_addrs = set()
            for family, socktype, proto, canonname, sockaddr in addr_info:
                addr = sockaddr[0]
                if bind_address == "0.0.0.0" or addr == bind_address:
                    if family == socket.AF_INET:
                        unique_addrs.add(addr)
                    elif family == socket.AF_INET6 and include_ipv6 and "%" not in addr:
                        unique_addrs.add(addr)

            if unique_addrs:
                addresses["hostname"] = sorted(list(unique_addrs))
        except (socket.gaierror, OSError):
            pass

        # Also add the bind address if it's specific
        if bind_address != "0.0.0.0" and bind_address not in str(addresses.values()):
            addresses["bound"] = [bind_address]
    except Exception:
        pass

    return addresses


# Bridges of container and VM hosts: their addresses are not reachable from the LAN.
VIRTUAL_PREFIXES = ("docker", "br-", "veth", "virbr", "cni", "flannel", "podman", "lxc", "vmnet", "vboxnet")


def client_addresses(bind_address: str = "0.0.0.0") -> List[str]:
    """IPv4 addresses a client on the LAN can use, main interfaces first.

    Leaves out loopback, link-local and container/VM bridges (unless nothing else is left).
    A specific ``bind_address`` (``--host``) is the only address that answers.
    """
    if bind_address != "0.0.0.0":
        return [bind_address]
    by_iface = get_network_addresses("0.0.0.0", include_ipv6=False)
    lan = [addr for name, addrs in by_iface.items() if not name.startswith(VIRTUAL_PREFIXES) for addr in addrs]
    return list(dict.fromkeys(lan or [addr for addrs in by_iface.values() for addr in addrs]))


def format_client_address(hostname: str, bind_address: str = "0.0.0.0") -> str:
    """The values to enter in a camera client: LAN IPv4 addresses, then the plain hostname.

    The FQDN is left out on purpose: a company DNS name often does not resolve on another network.
    The hostname is left out too when ptzsim listens on one address only (``--host``).
    """
    addresses = client_addresses(bind_address)
    if bind_address != "0.0.0.0":
        return addresses[0]
    return f"{', '.join(addresses)} or {hostname}" if addresses else hostname


def format_network_info_for_startup(bind_address: str = "0.0.0.0") -> str:
    """
    Format network information for display at simulator startup.

    Returns a multi-line string with the address to enter in a client first, then
    hostname, FQDN, and all interfaces with addresses.
    """
    hostname, fqdn = get_hostname_and_fqdn()
    interfaces = get_all_interfaces_detailed()

    lines = [
        "=" * 80,
        f"Address for clients: {format_client_address(hostname, bind_address)}",
        f"Hostname: {hostname}",
        f"FQDN: {fqdn}",
        "=" * 80,
        "",
        "Network Interfaces:",
    ]

    if interfaces:
        for iface_name in sorted(interfaces.keys()):
            iface = interfaces[iface_name]
            lines.append(iface.format_display())
    else:
        lines.append("  (No network interfaces found)")

    lines.append("=" * 80)

    return "\n".join(lines)


def format_network_summary() -> str:
    """
    Format a brief network summary with hostname and main IP addresses.

    Returns a single-line summary suitable for logs.
    """
    hostname, fqdn = get_hostname_and_fqdn()
    interfaces = get_all_interfaces_detailed()

    # Collect main IPv4 addresses (non-loopback, non-docker)
    main_ips = []
    for iface_name, iface in sorted(interfaces.items()):
        # Prefer eth, en, wlan interfaces
        if iface_name.startswith(("eth", "en", "wlan")):
            main_ips.extend([addr for addr, _ in iface.ipv4_addresses])

    # If no main interface, get any IPv4
    if not main_ips:
        for iface_name, iface in sorted(interfaces.items()):
            if not iface_name.startswith(("lo", "veth", "docker", "br-")):
                main_ips.extend([addr for addr, _ in iface.ipv4_addresses])
                if main_ips:
                    break

    if main_ips:
        return f"{hostname} ({', '.join(main_ips[:3])})"
    else:
        return hostname


def format_addresses_for_display(
    bind_address: str,
    ports: Dict[str, int],
) -> List[str]:
    """
    Format network addresses and ports for display in the startup message.

    Args:
        bind_address: The bind address (e.g., "0.0.0.0", "127.0.0.1", or specific IP)
        ports: Dictionary mapping transport names to port numbers

    Returns:
        List of formatted strings showing how to connect
    """
    lines: List[str] = []

    # If binding to all interfaces
    if bind_address == "0.0.0.0":
        all_addrs = get_resolved_addresses(bind_address)
        if all_addrs:
            lines.append(f"  Available on: {', '.join(all_addrs)}")

            # Show how to connect via each port, using the main interface
            for transport, port in sorted(ports.items()):
                lines.append(f"  {transport:15} → {all_addrs[0]}:{port}")
    else:
        # If binding to a specific address
        for transport, port in sorted(ports.items()):
            lines.append(f"  {transport:15} → {bind_address}:{port}")

    return lines


def get_resolved_addresses(bind_address: str) -> List[str]:
    """
    Get all addresses that this bind address resolves to.

    If bind_address is "0.0.0.0", returns all non-loopback IPv4 addresses, main
    interfaces first. Otherwise returns the specific address.
    """
    if bind_address != "0.0.0.0":
        return [bind_address]
    addr_dict = get_network_addresses(bind_address, include_ipv6=False)
    return list(dict.fromkeys(addr for addrs in addr_dict.values() for addr in addrs))
