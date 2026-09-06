"""RedisLlmSettingsStore — durable runtime LLM settings (opt-in).

Persists /settings/llm values (base_url, api_key, model) in Redis so they
survive API restarts. Only used when ``DATAHEK_METADATA_REDIS_URL`` is set
and the store is registered in the container.
"""
from __future__ import annotations

_FIELDS = ("base_url", "api_key", "model")


class RedisLlmSettingsStore:
    """Hash-backed store under ``datahek:llm:settings`` (one client per store)."""

    _KEY = "datahek:llm:settings"

    def __init__(self, url: str):
        import redis.asyncio

        self._client = redis.asyncio.from_url(url, decode_responses=True)

    async def load(self) -> dict | None:
        """Return stored {base_url, api_key, model} subset, or None when empty."""
        values = await self._client.hgetall(self._KEY)
        if not values:
            return None
        return {f: values[f] for f in _FIELDS if f in values}

    async def save(self, settings: dict) -> None:
        """Set fields individually; None/missing fields are left untouched."""
        fields = {k: v for k, v in settings.items() if k in _FIELDS and v is not None}
        if fields:
            await self._client.hset(self._KEY, mapping=fields)

    async def clear(self) -> None:
        await self._client.delete(self._KEY)

    async def close(self) -> None:
        await self._client.aclose()