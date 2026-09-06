"""LocalAuthProvider — OSS default: local users with plaintext dev passwords.

Production/Enterprise replace this via the AuthProvider contract (SSO/OIDC/SAML).
"""
import asyncio
import json
import logging

from datahek.contracts.auth import AuthProvider, AuthenticatedIdentity
from datahek.contracts.secrets import SecretRef, SecretsProvider
from datahek.kernel.config import Config, config_from_env


def _run(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


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

    _USERS_SECRET = "datahek_users"

    @classmethod
    def from_infisical(cls, secrets: SecretsProvider, secret_path: str = "auth") -> "LocalAuthProvider":
        """Load ``{"user": "password"}`` users from Infisical; env fallback when unavailable.

        The users secret lives at ``secret_path/datahek_users`` (Infisical path
        ``/<secret_path>``); any lookup/parse failure falls back to ``from_env()``.
        """
        async def _load() -> "LocalAuthProvider":
            folder = secret_path.strip("/")
            name = f"{folder}/{cls._USERS_SECRET}" if folder else cls._USERS_SECRET
            value = await secrets.get_secret(SecretRef(provider="infisical", name=name))
            users = json.loads(value.value)
            if not isinstance(users, dict) or not users:
                raise ValueError("datahek_users secret must hold a non-empty JSON object")
            return cls(users=users)

        try:
            return _run(_load())
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "Auth users unavailable from Infisical (%s); falling back to env/local users", exc)
            return cls.from_env()