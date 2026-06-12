"""LLM client factory.

Uses Anthropic's direct API. Configure with ANTHROPIC_API_KEY in .env.
"""

from __future__ import annotations

from anthropic import AsyncAnthropic

from core.config import settings


class LLMNotConfigured(RuntimeError):
    pass


_client: AsyncAnthropic | None = None


def get_client() -> AsyncAnthropic:
    """Return the configured Anthropic client.

    Reads ANTHROPIC_API_KEY from .env; raises LLMNotConfigured if missing.
    """
    global _client
    if _client is not None:
        return _client

    if not settings.anthropic_api_key:
        raise LLMNotConfigured(
            "ANTHROPIC_API_KEY is not set. Add it to .env "
            "(get a key at https://console.anthropic.com/)."
        )

    _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


def model_for(task: str) -> str:
    """Return the model id appropriate for a task."""
    if task in ("summary", "translate"):
        return settings.anthropic_model_summary
    return settings.anthropic_model_reasoning
