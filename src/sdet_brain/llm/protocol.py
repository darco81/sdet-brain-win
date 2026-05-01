"""Provider-agnostic LLM contract (T2-05).

Local-first: the only production implementation is ``MLXLLm`` running
Qwen3-Next-80B-A3B-Instruct-4bit on Apple Silicon. The Protocol shape
is kept minimal so future providers (vLLM, hosted APIs, etc.) can
satisfy it without ceremony.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


class LLMError(RuntimeError):
    """Raised when the LLM provider cannot complete a request."""


Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    """A single chat turn."""

    role: Role
    content: str


@runtime_checkable
class ILLM(Protocol):
    """Local LLM provider interface."""

    @property
    def model_name(self) -> str:
        """Human-readable model identifier."""
        ...

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> str:
        """Single-shot completion."""
        ...

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> str:
        """Multi-turn completion. Implementations apply the chat template."""
        ...

    def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> Iterator[str]:
        """Token-stream variant of :meth:`chat`. Yields incremental text."""
        ...

    def health_check(self) -> bool:
        """Return ``True`` if the model is loaded or can be loaded."""
        ...
