"""MLX-backed local LLM (T2-05).

Wraps the ``mlx_lm`` library so the rest of the brain can call
``generate(prompt) -> str`` and ``chat(messages) -> str`` without
caring that we're running quantised Qwen on Apple Silicon. Lazy load
on first call; subsequent calls reuse the warm model.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from threading import Lock
from typing import Any, Final

from sdet_brain.llm.protocol import ChatMessage, LLMError

logger = logging.getLogger(__name__)

DEFAULT_MODEL: Final[str] = "mlx-community/Qwen3-Next-80B-A3B-Instruct-4bit"
FALLBACK_MODEL: Final[str] = "mlx-community/gemma-4-26B-A4B-it-OptiQ-4bit"


class MLXLLm:
    """Local Qwen / Gemma instance via ``mlx_lm``.

    The model and tokenizer are loaded on the first ``generate`` /
    ``chat`` call. Cold start on an M4 Pro is ~30-60s for the 80B
    quantised model; subsequent calls hit the warm weights and stream
    at ~70 tok/s. The lock prevents two concurrent loads.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._lock = Lock()
        self._model: Any | None = None
        self._tokenizer: Any | None = None

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def _ensure_loaded(self) -> tuple[Any, Any]:
        if self._model is not None and self._tokenizer is not None:
            return self._model, self._tokenizer
        with self._lock:
            if self._model is None:
                try:
                    from mlx_lm import load
                except ImportError as exc:  # pragma: no cover - dep guard
                    raise LLMError(
                        "mlx_lm is not installed; install with `uv add mlx-lm`."
                    ) from exc
                logger.info("Loading MLX LLM %s (lazy, cold start)", self._model_name)
                # `load` returns a 2-tuple by default; `return_config=False`
                # explicit so mypy can pick the narrower overload variant.
                loaded = load(self._model_name, return_config=False)
                model, tokenizer = loaded[0], loaded[1]
                self._model = model
                self._tokenizer = tokenizer
        assert self._model is not None and self._tokenizer is not None  # noqa: S101
        return self._model, self._tokenizer

    def _apply_chat_template(self, messages: list[ChatMessage]) -> str:
        _model, tokenizer = self._ensure_loaded()
        tmpl = getattr(tokenizer, "apply_chat_template", None)
        chat_payload = [{"role": m.role, "content": m.content} for m in messages]
        if tmpl is None:
            # Fallback: simple flat formatter for tokenizers without template support.
            return "\n\n".join(f"{m.role}: {m.content}" for m in messages) + "\nassistant:"
        return str(tmpl(chat_payload, tokenize=False, add_generation_prompt=True))

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> str:
        if not prompt.strip():
            raise LLMError("prompt must not be empty")
        model, tokenizer = self._ensure_loaded()
        try:
            from mlx_lm import generate as _generate
        except ImportError as exc:  # pragma: no cover
            raise LLMError("mlx_lm is not installed.") from exc
        try:
            return str(
                _generate(
                    model,
                    tokenizer,
                    prompt=prompt,
                    max_tokens=max_tokens,
                    verbose=False,
                )
            )
        except Exception as exc:
            raise LLMError(f"MLX generate failed: {exc}") from exc

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> str:
        if not messages:
            raise LLMError("messages must not be empty")
        prompt = self._apply_chat_template(messages)
        return self.generate(prompt, max_tokens=max_tokens, temperature=temperature)

    def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> Iterator[str]:
        """Yield generated text incrementally.

        Uses ``mlx_lm.stream_generate`` when available so SSE clients
        can render tokens as they arrive. Falls back to a single yield
        of the full completion when streaming is not supported by the
        installed mlx_lm version.
        """
        if not messages:
            raise LLMError("messages must not be empty")
        model, tokenizer = self._ensure_loaded()
        prompt = self._apply_chat_template(messages)
        try:
            from mlx_lm import stream_generate
        except ImportError:
            yield self.generate(prompt, max_tokens=max_tokens, temperature=temperature)
            return
        try:
            for response in stream_generate(
                model,
                tokenizer,
                prompt=prompt,
                max_tokens=max_tokens,
            ):
                # Newer mlx_lm versions wrap the chunk; older yield strings.
                text = getattr(response, "text", response)
                if text:
                    yield str(text)
        except Exception as exc:
            raise LLMError(f"MLX stream_generate failed: {exc}") from exc

    def health_check(self) -> bool:
        """Return True when the model is already loaded.

        We deliberately do NOT trigger a load here - the daemon can
        boot in seconds, but the 80B model takes ~30-60s. The chat
        path is what pays the cold start.
        """
        return self._model is not None
