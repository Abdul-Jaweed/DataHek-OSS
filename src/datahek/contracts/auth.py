"""Authentication contract — OSS local, Enterprise SSO/SAML/OIDC."""
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class AuthenticatedIdentity:
    user_id: str
    authenticated: bool
    roles: frozenset[str] = field(default_factory=frozenset)
    permissions: frozenset[str] = field(default_factory=frozenset)
    provider: str = "local"


@runtime_checkable
class AuthProvider(Protocol):
    async def authenticate(self, *credentials: Any) -> AuthenticatedIdentity: ...