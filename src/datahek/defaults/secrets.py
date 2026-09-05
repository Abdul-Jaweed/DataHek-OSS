"""EnvSecretsProvider — OSS default: environment-variable secrets."""
import os

from datahek.contracts.secrets import SecretRef, SecretValue, SecretsProvider


class EnvSecretsProvider(SecretsProvider):
    def __init__(self, prefix: str = "DATAHEK_"):
        self._prefix = prefix

    async def get_secret(self, ref: SecretRef) -> SecretValue:
        name = self._prefix + ref.name.upper()
        if name not in os.environ:
            raise KeyError(f"Secret '{ref.name}' not found in environment")
        return SecretValue(value=os.environ[name])

    async def store_secret(self, ref: SecretRef, value: SecretValue) -> None:
        raise NotImplementedError("EnvSecretsProvider is read-only")