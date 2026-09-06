"""Infisical-backed auth users + LLM config (Task 7): from_infisical classmethods & container wiring."""
import asyncio
import os
import unittest
from unittest import mock

from datahek.contracts.auth import AuthProvider
from datahek.contracts.models import ModelProvider
from datahek.contracts.secrets import SecretRef, SecretValue, SecretsProvider
from datahek.defaults.auth import LocalAuthProvider
from datahek.defaults.container import build_app_container
from datahek.defaults.infisical import InfisicalSecretsProvider
from datahek.defaults.models import OpenAICompatibleModelProvider
from datahek.defaults.secrets import EnvSecretsProvider

_USERS_FIXTURE = '{"datahek": "datahek", "alice": "s3cret"}'
_LLM_FIXTURES = {
    "llm/llm_base_url": "https://llm.test/v1/",
    "llm/llm_api_key": "llm-key-123",
    "llm/llm_model": "model-x",
}


class _FakeSecrets:
    """Stand-in SecretsProvider: serves a fixed dict of values, records refs."""

    def __init__(self, values: dict[str, str] | None = None, error: Exception | None = None):
        self.values = dict(values or {})
        self.error = error
        self.refs: list[SecretRef] = []

    async def get_secret(self, ref: SecretRef) -> SecretValue:
        self.refs.append(ref)
        if self.error is not None:
            raise self.error
        if ref.name not in self.values:
            raise KeyError(f"Secret '{ref.name}' not found")
        return SecretValue(value=self.values[ref.name])

    async def store_secret(self, ref: SecretRef, value: SecretValue) -> None:
        raise NotImplementedError


async def _infisical_get_secret(self, ref: SecretRef) -> SecretValue:
    if ref.name == "auth/datahek_users":
        return SecretValue(value=_USERS_FIXTURE)
    if ref.name in _LLM_FIXTURES:
        return SecretValue(value=_LLM_FIXTURES[ref.name])
    raise KeyError(ref.name)


class TestAuthFromInfisical(unittest.TestCase):
    def test_loads_users_from_secret_and_authenticates(self):
        secrets = _FakeSecrets(values={"auth/datahek_users": _USERS_FIXTURE})
        provider = LocalAuthProvider.from_infisical(secrets)

        ident = asyncio.run(provider.authenticate("alice", "s3cret"))
        self.assertTrue(ident.authenticated)
        self.assertEqual(ident.user_id, "alice")
        ident = asyncio.run(provider.authenticate("datahek", "datahek"))
        self.assertTrue(ident.authenticated)
        self.assertFalse(asyncio.run(provider.authenticate("alice", "wrong")).authenticated)
        self.assertEqual(secrets.refs, [SecretRef(provider="infisical", name="auth/datahek_users")])

    def test_secret_ref_resolves_to_path_auth(self):
        secrets = _FakeSecrets(values={"auth/datahek_users": _USERS_FIXTURE})
        LocalAuthProvider.from_infisical(secrets)
        key, path = secrets.refs[0].name, None
        from datahek.defaults.infisical import split_secret_ref
        secret_key, secret_path = split_secret_ref(key)
        self.assertEqual((secret_key, secret_path), ("datahek_users", "/auth"))

    def test_custom_secret_path(self):
        secrets = _FakeSecrets(values={"vault/datahek_users": _USERS_FIXTURE})
        LocalAuthProvider.from_infisical(secrets, secret_path="vault")
        self.assertEqual(secrets.refs, [SecretRef(provider="infisical", name="vault/datahek_users")])

    def test_falls_back_to_env_when_secret_missing(self):
        secrets = _FakeSecrets()  # get_secret raises KeyError for anything
        with mock.patch.dict(os.environ, {"DATAHEK_AUTH_LOCAL_USERS": '{"envuser": "envpw"}'}):
            provider = LocalAuthProvider.from_infisical(secrets)
        ident = asyncio.run(provider.authenticate("envuser", "envpw"))
        self.assertTrue(ident.authenticated)

    def test_falls_back_to_env_when_provider_raises(self):
        secrets = _FakeSecrets(error=RuntimeError("infisical down"))
        with mock.patch.dict(os.environ, {"DATAHEK_AUTH_LOCAL_USERS": '{"envuser": "envpw"}'}):
            provider = LocalAuthProvider.from_infisical(secrets)
        self.assertTrue(asyncio.run(provider.authenticate("envuser", "envpw")).authenticated)

    def test_fails_closed_when_infisical_provider_raises(self):
        infisical = InfisicalSecretsProvider(host="https://infisical.test", client_id="cid",
                                             client_secret="csec", project_id="pid")
        with mock.patch.dict(os.environ, {"DATAHEK_AUTH_LOCAL_USERS": '{"envuser": "envpw"}'}), \
             mock.patch.object(InfisicalSecretsProvider, "get_secret",
                               new=mock.AsyncMock(side_effect=RuntimeError("infisical down"))):
            provider = LocalAuthProvider.from_infisical(infisical)

        self.assertFalse(asyncio.run(provider.authenticate("datahek", "datahek")).authenticated)
        self.assertFalse(asyncio.run(provider.authenticate("envuser", "envpw")).authenticated)

    def test_fails_closed_when_infisical_payload_invalid(self):
        infisical = InfisicalSecretsProvider(host="https://infisical.test", client_id="cid",
                                             client_secret="csec", project_id="pid")
        with mock.patch.object(InfisicalSecretsProvider, "get_secret",
                               new=mock.AsyncMock(return_value=SecretValue(value="not json"))):
            provider = LocalAuthProvider.from_infisical(infisical)

        self.assertFalse(asyncio.run(provider.authenticate("datahek", "datahek")).authenticated)

    def test_env_secrets_provider_triggers_fallback(self):
        secrets = EnvSecretsProvider()
        with mock.patch.dict(os.environ, {"DATAHEK_AUTH_LOCAL_USERS": '{"envuser": "envpw"}'}):
            provider = LocalAuthProvider.from_infisical(secrets)
        self.assertTrue(asyncio.run(provider.authenticate("envuser", "envpw")).authenticated)

    def test_garbage_payload_falls_back_to_defaults(self):
        secrets = _FakeSecrets(values={"auth/datahek_users": "not json at all"})
        provider = LocalAuthProvider.from_infisical(secrets)
        self.assertTrue(asyncio.run(provider.authenticate("datahek", "datahek")).authenticated)


class TestModelFromInfisical(unittest.TestCase):
    def test_resolves_llm_config_from_secrets(self):
        secrets = _FakeSecrets(values=dict(_LLM_FIXTURES))
        provider = OpenAICompatibleModelProvider.from_infisical(secrets)

        self.assertEqual(provider.model, "model-x")
        desc = asyncio.run(provider.describe())
        self.assertEqual(desc["base_url"], "https://llm.test/v1")
        self.assertEqual(desc["model"], "model-x")
        self.assertTrue(desc["api_key_set"])
        self.assertEqual(secrets.refs, [SecretRef(provider="infisical", name=n)
                                        for n in ("llm/llm_base_url", "llm/llm_api_key", "llm/llm_model")])

    def test_falls_back_to_env_when_secrets_missing(self):
        secrets = _FakeSecrets()
        with mock.patch.dict(os.environ, {
            "LLM_BASE_URL": "https://env.test/v1",
            "LLM_API_KEY": "env-key",
            "LLM_MODEL": "env-model",
        }):
            provider = OpenAICompatibleModelProvider.from_infisical(secrets)

        self.assertEqual(provider.model, "env-model")
        desc = asyncio.run(provider.describe())
        self.assertEqual(desc["base_url"], "https://env.test/v1")
        self.assertTrue(desc["api_key_set"])

    def test_partial_secrets_blend_with_env(self):
        secrets = _FakeSecrets(values={"llm/llm_model": "model-x"})
        with mock.patch.dict(os.environ, {"LLM_API_KEY": "env-key"}):
            provider = OpenAICompatibleModelProvider.from_infisical(secrets)

        self.assertEqual(provider.model, "model-x")
        desc = asyncio.run(provider.describe())
        self.assertTrue(desc["api_key_set"])


class TestContainerWiring(unittest.TestCase):
    def test_wiring_uses_infisical_when_configured(self):
        with mock.patch.dict(os.environ, {
            "INFISICAL_HOST": "https://infisical.test",
            "INFISICAL_CLIENT_ID": "cid",
            "INFISICAL_CLIENT_SECRET": "csec",
        }), mock.patch.object(InfisicalSecretsProvider, "get_secret", new=_infisical_get_secret):
            c = build_app_container()

        self.assertIsInstance(c.resolve(SecretsProvider), InfisicalSecretsProvider)
        auth: LocalAuthProvider = c.resolve(AuthProvider)
        self.assertIsInstance(auth, LocalAuthProvider)
        self.assertTrue(asyncio.run(auth.authenticate("alice", "s3cret")).authenticated)
        model: OpenAICompatibleModelProvider = c.resolve(ModelProvider)
        self.assertIsInstance(model, OpenAICompatibleModelProvider)
        self.assertEqual(model.model, "model-x")
        desc = asyncio.run(model.describe())
        self.assertEqual(desc["base_url"], "https://llm.test/v1")
        self.assertTrue(desc["api_key_set"])

    def test_wiring_defaults_to_env_when_not_configured(self):
        saved = {}
        for key in list(os.environ):
            if key.startswith("INFISICAL_") or key in ("DATAHEK_AUTH_LOCAL_USERS",
                                                       "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
                saved[key] = os.environ.pop(key)
        try:
            c = build_app_container()
        finally:
            os.environ.update(saved)

        self.assertIsInstance(c.resolve(SecretsProvider), EnvSecretsProvider)
        auth: LocalAuthProvider = c.resolve(AuthProvider)
        self.assertIsInstance(auth, LocalAuthProvider)
        self.assertTrue(asyncio.run(auth.authenticate("datahek", "datahek")).authenticated)
        model = c.resolve(ModelProvider)
        self.assertEqual(model.model, OpenAICompatibleModelProvider().model)


if __name__ == "__main__":
    unittest.main()
