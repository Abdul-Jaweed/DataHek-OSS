"""Secrets contract — connections hold references, never raw credentials."""
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SecretRef:
    provider: str
    name: str


@dataclass(frozen=True)
class SecretValue:
    value: str


@runtime_checkable
class SecretsProvider(Protocol):
    async def get_secret(self, ref: SecretRef) -> SecretValue: ...
    async def store_secret(self, ref: SecretRef, value: SecretValue) -> None: ...