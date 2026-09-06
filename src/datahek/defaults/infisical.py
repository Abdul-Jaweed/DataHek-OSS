"""InfisicalSecretsProvider — fetch/store secrets in Infisical via Universal Auth.

Enabled when ``INFISICAL_HOST`` / ``INFISICAL_CLIENT_ID`` /
``INFISICAL_CLIENT_SECRET`` are configured; otherwise the OSS default
``EnvSecretsProvider`` stays registered.

SecretRef encoding for Infisical refs: ``provider="infisical"``,
``name="<folder>/<key>"`` (folder optional). The Infisical secret path
(``secretPath``) is derived from the ref name by splitting on the last ``/``:
``name="creds/pg_password"`` resolves secret ``pg_password`` at path ``/creds``.
"""
import time

import httpx

from datahek.contracts.secrets import SecretRef, SecretValue, SecretsProvider
from datahek.kernel.config import Config, config_from_env
from datahek.kernel.errors import DatahekError, ErrorCode


class InfisicalConfig(Config):
    """INFISICAL_HOST · INFISICAL_CLIENT_ID · INFISICAL_CLIENT_SECRET · INFISICAL_PROJECT_ID · INFISICAL_ENVIRONMENT"""

    host: str = ""
    client_id: str = ""
    client_secret: str = ""
    project_id: str = ""
    environment: str = "dev"


def split_secret_ref(name: str) -> tuple[str, str]:
    """Return (secret_key, secret_path) for an Infisical ref name.

    A bare key resolves at the root path; ``creds/pg_password`` resolves
    ``pg_password`` at ``/creds``.
    """
    folder, _, key = name.rpartition("/")
    return key, ("/" + folder) if folder else "/"


class InfisicalSecretsProvider(SecretsProvider):
    """HTTP client for Infisical's Universal Auth + v3 secrets API."""

    _TOKEN_TTL_S = 55 * 60

    def __init__(self, host: str = "", client_id: str = "", client_secret: str = "",
                 project_id: str = "", environment: str = "dev"):
        self._host = host.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._project_id = project_id
        self._environment = environment
        self._cached_token: str | None = None
        self._token_at: float = 0.0

    async def _token(self) -> str:
        if self._cached_token is not None and time.monotonic() - self._token_at < self._TOKEN_TTL_S:
            return self._cached_token
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._host}/api/v1/auth/universal-auth/login",
                json={"clientId": self._client_id, "clientSecret": self._client_secret},
            )
            resp.raise_for_status()
            self._cached_token = resp.json()["accessToken"]
            self._token_at = time.monotonic()
        return self._cached_token

    def _require_project(self) -> None:
        if not self._project_id:
            raise DatahekError(ErrorCode.VALIDATION, "Infisical project_id not configured")

    async def get_secret(self, ref: SecretRef) -> SecretValue:
        self._require_project()
        key, secret_path = split_secret_ref(ref.name)
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._host}/api/v3/secrets/raw/{key}",
                params={"environment": self._environment, "secretPath": secret_path,
                        "workspaceId": self._project_id},
                headers={"Authorization": f"Bearer {await self._token()}"},
            )
            resp.raise_for_status()
            return SecretValue(value=resp.json()["secretValue"])

    async def store_secret(self, ref: SecretRef, value: SecretValue) -> None:
        self._require_project()
        key, secret_path = split_secret_ref(ref.name)
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._host}/api/v3/secrets/raw/{key}",
                params={"workspaceId": self._project_id},
                json={"secretValue": value.value, "environment": self._environment,
                      "secretPath": secret_path, "type": "shared"},
                headers={"Authorization": f"Bearer {await self._token()}"},
            )
            resp.raise_for_status()

    @classmethod
    def is_configured(cls) -> bool:
        cfg = config_from_env(InfisicalConfig, prefix="INFISICAL_")
        return bool(cfg.host and cfg.client_id and cfg.client_secret)

    @classmethod
    def from_env(cls) -> "InfisicalSecretsProvider":
        cfg = config_from_env(InfisicalConfig, prefix="INFISICAL_")
        return cls(host=cfg.host, client_id=cfg.client_id,
                   client_secret=cfg.client_secret, project_id=cfg.project_id,
                   environment=cfg.environment)