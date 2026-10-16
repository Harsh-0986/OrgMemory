"""LLM provider wiring.

Two providers are supported, selected by `LLM_PROVIDER`:

* ``nvidia`` - NVIDIA NIM through `ChatOpenAI`. NIM is natively
  OpenAI-compatible, so this is its real interface, not an adaptation.
* ``google`` - Google Gemini through `langchain-google-genai`, the official
  LangChain integration. Not the OpenAI-shaped endpoint: the user was explicit
  that this should be a real Gemini client.
* ``auto``   - whichever provider has a key, preferring the explicit setting.

The provider is resolved lazily and cached. A missing key raises
`LLMUnavailable` rather than failing at import, so the API can return a clean
503 and the agent can fall back to its deterministic writer.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Literal

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

ProviderName = Literal["nvidia", "google"]


class LLMUnavailable(RuntimeError):
    """Raised when the language model cannot be reached or is unconfigured."""


def resolve_provider(settings: Settings | None = None) -> ProviderName | None:
    """Which provider to use, or None if none is usable."""
    settings = settings or get_settings()
    choice = (settings.llm_provider or "auto").strip().lower()

    if choice == "nvidia":
        return "nvidia" if settings.nvidia_api_key else None
    if choice == "google":
        return "google" if settings.google_api_key else None

    # auto - fall back to whichever key exists.
    if settings.nvidia_api_key:
        return "nvidia"
    if settings.google_api_key:
        return "google"
    return None


def describe_providers(settings: Settings | None = None) -> list[str]:
    """Names of providers that currently have credentials. Used by /health."""
    settings = settings or get_settings()
    available = []
    if settings.nvidia_api_key:
        available.append("nvidia")
    if settings.google_api_key:
        available.append("google")
    return available


def _build_nvidia(settings: Settings) -> Any:
    """NVIDIA NIM via `ChatOpenAI` pointed at the NIM endpoint."""
    if not settings.nvidia_api_key:
        raise LLMUnavailable("NVIDIA_API_KEY is not configured.")

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
            # agent's own step budget still governs the run.
            max_retries=2,
            timeout=settings.agent_query_timeout_seconds * 4,
        )
    except Exception as exc:  # pragma: no cover - defensive
        raise LLMUnavailable(f"Could not initialise the NVIDIA client: {exc}") from exc


def _build_google(settings: Settings) -> Any:
    """Google Gemini via the official `langchain-google-genai` integration."""
    if not settings.google_api_key:
        raise LLMUnavailable("GOOGLE_API_KEY is not configured.")

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as exc:
        raise LLMUnavailable(
            "langchain-google-genai is not installed. Run `uv sync`."
        ) from exc

    try:
        return ChatGoogleGenerativeAI(
            model=settings.google_model,
            google_api_key=settings.google_api_key,
            temperature=settings.nvidia_temperature,
            max_output_tokens=settings.nvidia_max_tokens,
            timeout=settings.agent_query_timeout_seconds * 4,
            max_retries=2,
        )
    except Exception as exc:  # pragma: no cover - defensive
        raise LLMUnavailable(f"Could not initialise the Gemini client: {exc}") from exc


def _build(settings: Settings) -> Any:
    """Dispatch to the configured provider."""
    if not settings.llm_enabled:
        raise LLMUnavailable(
            "The language model is disabled (LLM_ENABLED=false). Investigations "
            "will run using the deterministic writer instead."
        )

    provider = resolve_provider(settings)
    if provider is None:
        raise LLMUnavailable(
            "No LLM is configured. Set NVIDIA_API_KEY or GOOGLE_API_KEY, or "
            "LLM_ENABLED=false to run without a model."
        )

    logger.info("Using LLM provider '%s'", provider)
    return _build_nvidia(settings) if provider == "nvidia" else _build_google(settings)


@lru_cache
def get_llm() -> Any:
    """Return the cached chat model used by every agent node."""
    return _build(get_settings())


def reset_llm_cache() -> None:
    """Clear the cached client (used by tests that patch configuration)."""
    get_llm.cache_clear()


def llm_is_configured() -> bool:
    """True when the model is enabled and some provider has credentials."""
    settings = get_settings()
    return bool(settings.llm_enabled and resolve_provider(settings))