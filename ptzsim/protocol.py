# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Plugin interface for control protocols.

Every protocol the simulator speaks (VISCA over its transports, ONVIF, NDI, ...)
is a :class:`ProtocolPlugin` subclass registered with :func:`register`. The
``serve`` command builds its options from the registered plugins and starts the
ones the user enabled; all of them drive the same simulated camera
(:attr:`ServeContext.camera`). See ``docs/adding-a-protocol.md`` for a
step-by-step guide.

Plugins are found in three places, in this order:

1. the built-in protocols (``ptzsim.builtin_protocols``),
2. modules listed in :data:`EXTRA_MODULES` (in-tree protocols added later),
3. installed packages that declare an entry point in the group
   ``ptzsim.protocols`` (third-party protocols, no change to ptzsim needed).
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Type

from .state import CameraState

log = logging.getLogger("ptzsim")

ENTRY_POINT_GROUP = "ptzsim.protocols"
BUILTIN_MODULES = ("ptzsim.builtin_protocols",)
# In-tree protocol modules that register plugins on import; add new ones here.
EXTRA_MODULES: tuple = ()


@dataclass
class Endpoint:
    """One address a plugin listens on, shown in the dashboard title and log."""

    label: str  # protocol name for humans, e.g. "Sony VISCA/IP"
    address: str = ""  # e.g. "udp://0.0.0.0:52381" or a device path
    port: Optional[int] = None  # network port, if any

    def __str__(self) -> str:
        return f"{self.label} {self.address}" if self.address else self.label


class ServeContext:
    """What a plugin gets when it is started.

    ``camera`` is the :class:`ptzsim.visca.ViscaCamera` that every protocol
    shares: ``camera.state`` is the camera model (:class:`ptzsim.state.CameraState`,
    VISCA units), ``camera.record(label, text, ok)`` adds a line to the command
    log and ``camera.instant`` tells whether moves jump to their target.
    ``simulator`` (:class:`ptzsim.transports.Simulator`) runs the motor physics
    and accepts raw VISCA packets via ``simulator.process(packet, send)``.
    """

    def __init__(self, camera, simulator, args: argparse.Namespace):
        self.camera = camera
        self.simulator = simulator
        self.args = args
        #: Plugins started by :meth:`start_plugins`, and the endpoints they returned.
        self.plugins: List[ProtocolPlugin] = []
        self.endpoints: List[Endpoint] = []

    async def start_plugins(self) -> None:
        """Start every plugin selected in :attr:`args` (see :func:`selected`)."""
        for plugin_class in selected(self.args):
            plugin = plugin_class()
            # Registered before start() so a plugin that fails halfway is stopped too.
            self.plugins.append(plugin)
            self.endpoints += await plugin.start(self)

    def stop_plugins(self) -> None:
        """Stop the started plugins, last started first."""
        while self.plugins:
            self.plugins.pop().stop()

    @property
    def state(self) -> CameraState:
        return self.camera.state

    @property
    def host(self) -> str:
        """Address to listen on (``--host``)."""
        return self.args.host

    @property
    def name(self) -> str:
        """Camera name (``--name``), for protocols that announce one."""
        return self.args.name

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return asyncio.get_running_loop()


class ProtocolPlugin:
    """Base class of a control protocol.

    A subclass sets :attr:`name` and :attr:`title`, adds its command line options
    in :meth:`add_arguments`, says in :meth:`enabled` whether the user switched it
    on, and starts its servers in :meth:`start`. One instance is created per
    ``serve`` run, so :meth:`start` may keep handles on ``self`` for :meth:`stop`.
    """

    #: Unique id (lowercase, ``-`` allowed); also the default option name.
    name: str = ""
    #: Human readable name, used as the heading of the plugin's options in ``--help``.
    title: str = ""
    #: Started when the user enables no protocol at all (only one plugin may set it).
    default: bool = False

    @classmethod
    def add_arguments(cls, group: argparse._ArgumentGroup) -> None:
        """Add the plugin's options to its ``--help`` group."""

    @classmethod
    def enabled(cls, args: argparse.Namespace) -> bool:
        """True if the parsed options switch this protocol on."""
        raise NotImplementedError

    @classmethod
    def enable_default(cls, args: argparse.Namespace) -> None:
        """Switch the protocol on in ``args`` (used for the :attr:`default` plugin)."""
        raise NotImplementedError

    def __init__(self) -> None:
        #: Servers and transports (anything with ``close()``) closed by :meth:`stop`.
        self.servers: List[Any] = []

    async def start(self, ctx: ServeContext) -> List[Endpoint]:
        """Start listening; return the endpoints to show to the user.

        Append the servers/transports you open to :attr:`servers`.
        """
        raise NotImplementedError

    def stop(self) -> None:
        """Called once when the simulator shuts down; closes :attr:`servers`.

        Override (and call ``super().stop()``) to say goodbye on the network first.
        """
        while self.servers:
            self.servers.pop().close()


class PortPlugin(ProtocolPlugin):
    """A protocol switched on by ``--<option> [PORT]``, the common case.

    Set :attr:`default_port` (and :attr:`option` if it differs from ``--<name>``);
    the option is added automatically and :meth:`port` returns the chosen port.
    """

    #: Port used when the option is given without a value.
    default_port: int = 0
    #: Command line option; defaults to ``--<name>``.
    option: str = ""
    #: Help text of the option; ``{port}`` is replaced by :attr:`default_port`.
    help: str = ""

    @classmethod
    def option_name(cls) -> str:
        return cls.option or f"--{cls.name}"

    @classmethod
    def dest(cls) -> str:
        return cls.option_name().lstrip("-").replace("-", "_")

    @classmethod
    def add_arguments(cls, group: argparse._ArgumentGroup) -> None:
        group.add_argument(cls.option_name(), type=int, metavar="PORT", nargs="?",
                           const=cls.default_port, dest=cls.dest(),
                           help=cls.help.format(port=cls.default_port) or None)
        cls.add_options(group)

    @classmethod
    def add_options(cls, group: argparse._ArgumentGroup) -> None:
        """Add further options besides ``--<name> [PORT]``."""

    @classmethod
    def enabled(cls, args: argparse.Namespace) -> bool:
        return getattr(args, cls.dest(), None) is not None

    @classmethod
    def enable_default(cls, args: argparse.Namespace) -> None:
        setattr(args, cls.dest(), cls.default_port)

    @classmethod
    def port(cls, args: argparse.Namespace) -> int:
        return getattr(args, cls.dest())


# ------------------------------------------------------------------ registry
_registry: Dict[str, Type[ProtocolPlugin]] = {}
_loaded = False


def register(cls: Type[ProtocolPlugin]) -> Type[ProtocolPlugin]:
    """Class decorator: make a plugin known to ``ptzsim serve``.

    Plugins are listed (in ``--help``, the endpoint title and the start order) in
    the order they are registered.
    """
    if not (isinstance(cls, type) and issubclass(cls, ProtocolPlugin)):
        raise TypeError(f"{cls!r} is not a ProtocolPlugin subclass")
    if not cls.name or not cls.title:
        raise ValueError(f"{cls.__name__} needs a name and a title")
    other = _registry.get(cls.name)
    if other is not None and other is not cls:
        raise ValueError(f"protocol name {cls.name!r} is already used by {other.__name__}")
    if cls.default and any(p.default and p is not cls for p in _registry.values()):
        raise ValueError(f"{cls.__name__}: only one protocol can be the default")
    _registry[cls.name] = cls
    return cls


def unregister(name: str) -> None:
    """Remove a plugin again (for tests)."""
    _registry.pop(name, None)


def _entry_points() -> List[Any]:
    try:
        from importlib import metadata
    except ImportError:  # pragma: no cover - Python < 3.8
        return []
    try:
        eps = metadata.entry_points()
    except Exception as err:  # broken installed metadata must not stop the simulator
        log.warning("cannot read protocol entry points: %s", err)
        return []
    if hasattr(eps, "select"):  # Python >= 3.10
        return list(eps.select(group=ENTRY_POINT_GROUP))
    return list(eps.get(ENTRY_POINT_GROUP, ()))  # Python 3.8 / 3.9: a dict


def load() -> None:
    """Import the built-in, in-tree and installed plugins (once)."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    for module in BUILTIN_MODULES + tuple(EXTRA_MODULES):
        importlib.import_module(module)
    for ep in _entry_points():
        try:
            obj = ep.load()
            # The entry point may name a plugin class or a module that registers itself.
            if isinstance(obj, type) and issubclass(obj, ProtocolPlugin):
                register(obj)
        except Exception as err:  # a broken third-party plugin must not stop the others
            log.warning("protocol plugin %s could not be loaded: %s", ep.name, err)


def plugins() -> List[Type[ProtocolPlugin]]:
    """All registered plugins, in registration order."""
    load()
    return list(_registry.values())


def get(name: str) -> Type[ProtocolPlugin]:
    load()
    return _registry[name]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Add one option group per registered plugin to ``parser``."""
    for plugin in plugins():
        plugin.add_arguments(parser.add_argument_group(plugin.title))


def selected(args: argparse.Namespace) -> List[Type[ProtocolPlugin]]:
    """The plugins enabled in ``args``; the default plugin if none is."""
    chosen = [p for p in plugins() if p.enabled(args)]
    if not chosen:
        chosen = [p for p in plugins() if p.default]
        for plugin in chosen:
            plugin.enable_default(args)
    return chosen
