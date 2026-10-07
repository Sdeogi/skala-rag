"""Runtime settings from environment variables and their validation (design E.2)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

MODEL_ENV_VAR = "RAG_MODEL_ID"  # the one environment variable every LLM caller reads
DEFAULT_MODEL_ID = "gpt-5.6-luna"  # the one place the default model name is written


def resolve_model_id(explicit: str | None = None, env: Mapping[str, str] | None = None) -> str:
    """Model to call: an explicit argument, else ``RAG_MODEL_ID``, else ``DEFAULT_MODEL_ID``."""
    source = os.environ if env is None else env
    return explicit or source.get(MODEL_ENV_VAR) or DEFAULT_MODEL_ID


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None
    tavily_api_key: str | None
    model_id: str
    pdf_font: str | None
    langsmith_project: str | None


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    source = os.environ if env is None else env
    return Settings(
        openai_api_key=source.get("OPENAI_API_KEY") or None,
        tavily_api_key=source.get("TAVILY_API_KEY") or None,
        model_id=resolve_model_id(env=source),
        pdf_font=source.get("RAG_PDF_FONT") or None,
        langsmith_project=source.get("LANGCHAIN_PROJECT") or None,
    )


def missing_settings(
    settings: Settings,
    mode: str,
    *,
    semantic_review: bool = False,
    llm_output: bool = False,
    services_need_llm: bool = False,
) -> list[str]:
    """Names of required settings that are absent for the requested run.

    The real A/B/C services call the judgment LLM even in replay mode (only web
    search and page fetches are replayed from cache), so ``services_need_llm``
    is True for every non-fixture run.
    """
    missing: list[str] = []
    needs_openai = mode == "live" or semantic_review or llm_output or services_need_llm
    if needs_openai and not settings.openai_api_key:
        missing.append("OPENAI_API_KEY")
    if mode == "live" and not settings.tavily_api_key:
        missing.append("TAVILY_API_KEY")
    return missing
