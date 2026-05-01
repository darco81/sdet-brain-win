"""Local-first LLM layer (T2-05)."""

from sdet_brain.llm.factory import get_llm
from sdet_brain.llm.protocol import (
    ILLM,
    ChatMessage,
    LLMError,
)

__all__ = ["ILLM", "ChatMessage", "LLMError", "get_llm"]
