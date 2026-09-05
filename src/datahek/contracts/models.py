"""Model provider contract — LLM-agnostic completion and streaming."""
from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol, TypedDict, runtime_checkable


class ModelMessage(TypedDict):
    role: str  # "system" | "user" | "assistant"
    content: str


class ModelRequest(TypedDict, total=False):
    messages: list[ModelMessage]
    temperature: float
    max_tokens: int
    response_format: str  # "text" | "json_object"


@dataclass(frozen=True)
class ModelResponse:
    content: str
    usage: dict = field(default_factory=dict)


class ModelProviderError(Exception):
    """Typed model-provider failure (HTTP status preserved, no raw leak)."""

    def __init__(self, message: str, status_code: int | None = None):
        self.status_code = status_code
        super().__init__(message)


@runtime_checkable
class ModelProvider(Protocol):
    async def complete(self, request: ModelRequest) -> ModelResponse: ...
    async def stream(self, request: ModelRequest) -> AsyncIterator[str]: ...