"""LocalAuthProvider — OSS default: local users with plaintext dev passwords.

Production/Enterprise replace this via the AuthProvider contract (SSO/OIDC/SAML).
"""
import json

from datahek.contracts.auth import AuthProvider, AuthenticatedIdentity
from datahek.kernel.config import Config, config_from_env


class AuthConfig(Config):
    """DATAHEK_AUTH_MODE=none|local · DATAHEK_AUTH_LOCAL_USERS='{"user":"pass"}'"""

    mode: str = "none"
    local_users: str = "{}"


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

    async def authenticate_api_key(self, token: str) -> AuthenticatedIdentity:
        for user_id, password in self._users.items():
            if password == token:
                return AuthenticatedIdentity(
                    user_id=user_id,
                    authenticated=True,
                    roles=self._roles.get(user_id, frozenset({"analyst"})),
                    provider="local-key",
                )
        return AuthenticatedIdentity(user_id="anonymous", authenticated=False, provider="local-key")

    @classmethod
    def from_env(cls) -> "LocalAuthProvider":
        cfg = config_from_env(AuthConfig, prefix="DATAHEK_AUTH_")
        try:
            users = json.loads(cfg.local_users)
        except json.JSONDecodeError:
            users = {}
        if not isinstance(users, dict) or not users:
            # Default local credential: datahek / datahek (override via DATAHEK_AUTH_LOCAL_USERS)
            users = {"datahek": "datahek"}
        return cls(users=users)