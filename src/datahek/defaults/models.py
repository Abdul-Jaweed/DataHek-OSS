"""OpenAI-compatible model provider — default OSS implementation.

Talks to any OpenAI-compatible /chat/completions endpoint (opencode, Groq,
local LLMs). Uses httpx (optional dependency: ``datahek-core[llm]``).
HTTP failures surface as typed ``ModelProviderError`` — never raw driver text.
"""
import logging
from typing import Any

from datahek.contracts.models import ModelProvider, ModelProviderError, ModelRequest, ModelResponse
from datahek.contracts.secrets import SecretRef, SecretsProvider
from datahek.defaults.async_util import run_sync
from datahek.kernel.config import Config, config_from_env

_LLM_SECRET_FIELDS = (
    ("llm_base_url", "base_url"),
    ("llm_api_key", "api_key"),
    ("llm_model", "model"),
)


class ModelConfig(Config):
    base_url: str = "https://opencode.ai/zen/go/v1"
    api_key: str = ""
    model: str = "mimo-v2.5"
    timeout_s: float = 120.0


class OpenAICompatibleModelProvider(ModelProvider):
    def __init__(self, config: ModelConfig | None = None,
                 settings_store: "RedisLlmSettingsStore | None" = None):
        self._config = config or config_from_env(ModelConfig, prefix="LLM_")
        self._settings_store = settings_store

    @classmethod
    def from_infisical(cls, secrets: SecretsProvider) -> "OpenAICompatibleModelProvider":
        """Build from Infisical ``/llm`` secrets (llm_base_url/api_key/model), env fallback.

        Env (``LLM_*``) is the baseline; each Infisical value that resolves
        successfully overrides its field. Unavailable secrets keep env values.
        """
        async def _resolve():
            cfg = config_from_env(ModelConfig, prefix="LLM_")
            overrides: dict[str, str] = {}
            for secret_key, field in _LLM_SECRET_FIELDS:
                ref = SecretRef(provider="infisical", name=f"llm/{secret_key}")
                try:
                    value = await secrets.get_secret(ref)
                except Exception as exc:
                    logging.getLogger(__name__).warning(
                        "LLM secret '%s' unavailable from Infisical (%s); using env value",
                        secret_key, exc)
                    continue
                if value.value:
                    overrides[field] = value.value
            if not overrides:
                return cfg
            from dataclasses import replace
            if overrides.get("base_url"):
                overrides["base_url"] = overrides["base_url"].rstrip("/")
            return replace(cfg, **overrides)

        return cls(config=run_sync(_resolve()))

    async def configure(self, base_url: str | None = None, api_key: str | None = None,
                        model: str | None = None) -> None:
        from dataclasses import replace
        self._config = replace(
            self._config,
            base_url=(base_url or self._config.base_url).rstrip("/"),
            api_key=self._config.api_key if api_key is None else api_key,
            model=model or self._config.model,
        )

    async def reload_from_store(self) -> None:
        """Apply persisted Redis settings as overrides on top of env config."""
        if self._settings_store is None:
            return
        stored = await self._settings_store.load()
        if not stored:
            return
        overrides = {k: v for k, v in stored.items()
                     if k in ("base_url", "api_key", "model") and v is not None}
        if not overrides:
            return
        from dataclasses import replace
        if overrides.get("base_url"):
            overrides["base_url"] = overrides["base_url"].rstrip("/")
        self._config = replace(self._config, **overrides)

    def model_id(self) -> str:
        return self._config.model

    async def describe(self) -> dict:
        return {
            "base_url": self._config.base_url,
            "model": self._config.model,
            "api_key_set": bool(self._config.api_key),
        }

    @property
    def model(self) -> str:
        return self._config.model

    def _headers(self) -> dict:
        """Request headers — some OpenAI-compatible gateways require a session id."""
        import uuid

        return {
            "Authorization": f"Bearer {self._config.api_key}",
            "x-opencode-session": str(uuid.uuid4()),
        }

    async def _post(self, payload: dict) -> dict:
        import httpx

        url = f"{self._config.base_url.rstrip('/')}/chat/completions"
        async with httpx.AsyncClient(timeout=self._config.timeout_s) as client:
            resp = await client.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    def _convert_error(e: Exception) -> Exception:
        import httpx

        if isinstance(e, httpx.HTTPStatusError):
            return ModelProviderError("model provider error", status_code=e.response.status_code)
        if isinstance(e, httpx.HTTPError):
            return ModelProviderError("model provider unreachable")
        return e

    async def complete(self, request: ModelRequest) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": request["messages"],
        }
        if request.get("temperature") is not None:
            payload["temperature"] = request["temperature"]
        if request.get("max_tokens") is not None:
            payload["max_tokens"] = request["max_tokens"]
        if request.get("response_format") == "json_object":
            payload["response_format"] = {"type": "json_object"}

        try:
            data = await self._post(payload)
        except Exception as e:
            converted = self._convert_error(e)
            if converted is not e:
                raise converted from e
            raise
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError("Model response missing content") from e
        return ModelResponse(content=content or "", usage=data.get("usage", {}))

    async def stream(self, request: ModelRequest):
        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": request["messages"],
            "stream": True,
        }
        try:
            data = await self._post(payload)
        except Exception as e:
            converted = self._convert_error(e)
            if converted is not e:
                raise converted from e
            raise
        if isinstance(data, dict) and data.get("choices"):
            content = data["choices"][0].get("message", {}).get("content", "")
            if content:
                yield content