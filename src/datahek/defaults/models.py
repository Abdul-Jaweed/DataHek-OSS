"""OpenAI-compatible model provider — default OSS implementation.

Talks to any OpenAI-compatible /chat/completions endpoint (opencode, Groq,
local LLMs). Uses httpx (optional dependency: ``datahek-core[llm]``).
"""
import logging
from typing import Any

from datahek.contracts.models import ModelProvider, ModelRequest, ModelResponse
from datahek.kernel.config import Config, config_from_env

logger = logging.getLogger(__name__)


class ModelConfig(Config):
    base_url: str = "https://opencode.ai/zen/go/v1"
    api_key: str = ""
    model: str = "mimo-v2.5"
    timeout_s: float = 60.0


class OpenAICompatibleModelProvider(ModelProvider):
    def __init__(self, config: ModelConfig | None = None):
        self._config = config or config_from_env(ModelConfig, prefix="LLM_")

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

        data = await self._post(payload)
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
        data = await self._post(payload)
        if isinstance(data, dict) and data.get("choices"):
            content = data["choices"][0].get("message", {}).get("content", "")
            if content:
                yield content