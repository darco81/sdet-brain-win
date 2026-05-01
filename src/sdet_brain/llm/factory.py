"""LLM factory (T2-05).

Returns an :class:`ILLM` configured by ``Settings``. Only one provider
exists today (``MLXLLm``); the factory still routes through here so
future providers can land without touching every call site.
"""

from __future__ import annotations

import logging

from sdet_brain.llm.mlx_provider import DEFAULT_MODEL, MLXLLm
from sdet_brain.llm.protocol import ILLM

logger = logging.getLogger(__name__)


def get_llm(model_name: str | None = None) -> ILLM:
    """Build an :class:`ILLM` for ``model_name`` (default: Qwen3-Next-80B-Instruct-4bit)."""
    name = model_name or DEFAULT_MODEL
    logger.info("LLM factory selected MLX provider with model=%s", name)
    return MLXLLm(model_name=name)
