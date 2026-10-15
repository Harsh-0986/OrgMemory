"""LLM provider wiring for NVIDIA NIM.

NVIDIA NIM exposes an OpenAI-compatible chat completions endpoint, so we reuse
`ChatOpenAI` and simply repoint `base_url`. That keeps the whole agent on the
standard LangChain interface and avoids a bespoke HTTP client.

The provider is created lazily and cached, and it never raises at import time -
a missing API key must surface as a clean API error, not an import crash.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    """Raised when the language model cannot be reached or is unconfigured."""


@lru_cache
def get_llm() -> Any:
    """Return the cached chat model used by every agent node."""
    settings = get_settings()
    return _build_llm(settings)


def _build_llm(settings: Settings) -> Any:
    """Construct a `ChatOpenAI` client aimed at the configured NIM endpoint."""
    if not settings.llm_enabled:
        raise LLMUnavailable(
            "The language model is disabled (LLM_ENABLED=false). Investigations "
            "will run using the deterministic writer instead."
        )
    if not settings.nvidia_api_key:
        raise LLMUnavailable(
            "NVIDIA_API_KEY is not configured. Add it to your .env file to enable "
            "natural-language investigation."
        )

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise LLMUnavailable("langchain-openai is not installed") from exc

    try:
        return ChatOpenAI(
            model=settings.nvidia_model,
            api_key=settings.nvidia_api_key,
            base_url=settings.nvidia_base_url,
            temperature=settings.nvidia_temperature,
            max_tokens=settings.nvidia_max_tokens,
            # Bounded retries: a flaky endpoint must fail fast enough that the
            # agent's overall step budget still governs the run.
            max_retries=2,
            timeout=settings.agent_query_timeout_seconds * 4,
        )
    except Exception as exc:  # pragma: no cover - defensive
        raise LLMUnavailable(f"Could not initialise the chat model: {exc}") from exc


def reset_llm_cache() -> None:
    """Clear the cached client (used by tests that patch configuration)."""
    get_llm.cache_clear()


def llm_is_configured() -> bool:
    """True when a model endpoint and API key are both present and enabled."""
    settings = get_settings()
    return bool(settings.llm_enabled and settings.nvidia_api_key and settings.nvidia_base_url)