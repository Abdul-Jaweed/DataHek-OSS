"""OpenAI-compatible model provider — default OSS implementation.

Talks to any OpenAI-compatible /chat/completions endpoint (opencode, Groq,
local LLMs). Uses httpx (optional dependency: ``datahek-core[llm]``).
HTTP failures surface as typed ``ModelProviderError`` — never raw driver text.
"""
from typing import Any

from datahek.contracts.models import ModelProvider, ModelProviderError, ModelRequest, ModelResponse
from datahek.kernel.config import Config, config_from_env


class ModelConfig(Config):
    base_url: str = "https://opencode.ai/zen/go/v1"
    api_key: str = ""
    model: str = "mimo-v2.5"
    timeout_s: float = 60.0


class OpenAICompatibleModelProvider(ModelProvider):
    def __init__(self, config: ModelConfig | None = None):
        self._config = config or config_from_env(ModelConfig, prefix="LLM_")

    async def configure(self, base_url: str | None = None, api_key: str | None = None,
                        model: str | None = None) -> None:
        from dataclasses import replace
        self._config = replace(
            self._config,
            base_url=(base_url or self._config.base_url).rstrip("/"),
            api_key=self._config.api_key if api_key is None else api_key,
            model=model or self._config.model,
        )

    async def describe(self) -> dict:
        return {
            "base_url": self._config.base_url,
            "model": self._config.model,
            "api_key_set": bool(self._config.api_key),
        }

    @property
    def model(self) -> str:
        return self._config.model

    async def _post(self, payload: dict) -> dict:
        import httpx

        headers = {"Authorization": f"Bearer {self._config.api_key}"}
        url = f"{self._config.base_url.rstrip('/')}/chat/completions"
        async with httpx.AsyncClient(timeout=self._config.timeout_s) as client:
            resp = await client.post(url, json=payload, headers=headers)
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