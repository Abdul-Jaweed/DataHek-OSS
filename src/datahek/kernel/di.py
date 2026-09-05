"""Dependency injection container — interface → implementation resolution."""
from dataclasses import dataclass
from typing import Any, Callable


class NotResolvable(Exception):
    pass


@dataclass
class _Entry:
    implementation: Any
    singleton: bool = False
    cached: Any = None


class Container:
    """Minimal DI container: register instances or factories per interface.

    Enterprise replaces OSS defaults via ``override`` — the agent code never
    knows which implementation is active.
    """

    def __init__(self):
        self._entries: dict[type, _Entry] = {}

    def register(self, interface: type, implementation: Any, singleton: bool = False) -> None:
        self._entries[interface] = _Entry(implementation, singleton)

    def override(self, interface: type, implementation: Any) -> None:
        self._entries[interface] = _Entry(implementation, singleton=False)

    def has(self, interface: type) -> bool:
        return interface in self._entries

    def resolve(self, interface: type) -> Any:
        entry = self._entries.get(interface)
        if entry is None:
            raise NotResolvable(f"No implementation registered for {interface.__name__}")
        if entry.singleton and entry.cached is not None:
            return entry.cached
        impl = entry.implementation
        if callable(impl) and not isinstance(impl, interface):
            impl = impl()
            if entry.singleton:
                entry.cached = impl
        return impl