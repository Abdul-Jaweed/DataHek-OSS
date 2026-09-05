"""Extension registry — Enterprise attaches implementations without touching OSS."""
from typing import Any


class AlreadyRegistered(Exception):
    pass


class ExtensionRegistry:
    """Named extension points: auth providers, policy engines, audit sinks, ..."""

    def __init__(self):
        self._items: dict[str, Any] = {}

    def register(self, name: str, implementation: Any) -> None:
        if name in self._items:
            raise AlreadyRegistered(f"Extension '{name}' already registered")
        self._items[name] = implementation

    def get(self, name: str) -> Any:
        return self._items[name]

    def names(self) -> list[str]:
        return list(self._items)