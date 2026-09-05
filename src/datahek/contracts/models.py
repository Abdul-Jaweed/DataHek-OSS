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


@runtime_checkable
class ModelProvider(Protocol):
    async def complete(self, request: ModelRequest) -> ModelResponse: ...
    async def stream(self, request: ModelRequest) -> AsyncIterator[str]: ...