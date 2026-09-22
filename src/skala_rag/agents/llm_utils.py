"""Small helpers shared by the live-mode LLM agents."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel


def usage_from_message(message: Any) -> dict[str, int]:
    """Extract token usage from a LangChain AIMessage (zeros when unavailable)."""
    meta = getattr(message, "usage_metadata", None) or {}
    if not isinstance(meta, Mapping):
        meta = {}
    return {
        "input_tokens": int(meta.get("input_tokens", 0) or 0),
        "output_tokens": int(meta.get("output_tokens", 0) or 0),
        "total_tokens": int(meta.get("total_tokens", 0) or 0),
    }


def invoke_structured(model: Any, schema: type[BaseModel], messages: list[Any]) -> tuple[BaseModel, dict[str, int]]:
    """Invoke ``model`` with structured output and return ``(parsed, usage)``.

    Uses ``include_raw=True`` so token usage can be read from the raw message.
    Fake models used in tests may return the parsed value (or a dict) directly.
    """
    runnable = model.with_structured_output(schema, include_raw=True)
    response = runnable.invoke(messages)
    usage: dict[str, int] = {}
    if isinstance(response, Mapping) and "parsed" in response:
        error = response.get("parsing_error")
        if error:
            raise error if isinstance(error, Exception) else ValueError(str(error))
        parsed = response.get("parsed")
        usage = usage_from_message(response.get("raw"))
    else:
        parsed = response
    if not isinstance(parsed, schema):
        parsed = schema.model_validate(parsed)
    return parsed, usage
