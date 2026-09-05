"""LocalAuthProvider — OSS default: local users with plaintext dev passwords.

Production/Enterprise replace this via the AuthProvider contract (SSO/OIDC/SAML).
"""
from datahek.contracts.auth import AuthProvider, AuthenticatedIdentity


class LocalAuthProvider(AuthProvider):
    def __init__(self, users: dict[str, str] | None = None, roles: dict[str, frozenset[str]] | None = None):
        self._users = dict(users or {})
        self._roles = dict(roles or {})

    async def authenticate(self, user_id: str, password: str) -> AuthenticatedIdentity:
        if user_id in self._users and self._users[user_id] == password:
            return AuthenticatedIdentity(
                user_id=user_id,
                authenticated=True,
                roles=self._roles.get(user_id, frozenset({"analyst"})),
                provider="local",
            )
        return AuthenticatedIdentity(user_id=user_id, authenticated=False, provider="local")