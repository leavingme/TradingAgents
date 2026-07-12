"""Shared helpers for invoking an agent with structured output and a graceful fallback.

The Portfolio Manager, Trader, and Research Manager all follow the same
canonical pattern:

1. At agent creation, wrap the LLM with ``with_structured_output(Schema)``
   so the model returns a typed Pydantic instance. If the provider does
   not support structured output (rare; mostly older Ollama models), the
   wrap is skipped and the agent uses free-text generation instead.
2. At invocation, run the structured call and render the result back to
   markdown. If the structured call itself fails for any reason
   (malformed JSON from a weak model, transient provider issue), fall
   back to a plain ``llm.invoke`` so the pipeline never blocks.

Centralising the pattern here keeps the agent factories small and ensures
all three agents log the same warnings when fallback fires.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def bind_structured(llm: Any, schema: type[T], agent_name: str) -> Any | None:
    """Return ``llm.with_structured_output(schema)`` or ``None`` if unsupported.

    Logs a warning when the binding fails so the user understands the agent
    will use free-text generation for every call instead of one-shot fallback.
    """
    try:
        return llm.with_structured_output(schema)
    except (NotImplementedError, AttributeError) as exc:
        logger.warning(
            "%s: provider does not support with_structured_output (%s); "
            "falling back to free-text generation",
            agent_name, exc,
        )
        return None


def invoke_structured_or_freetext(
    structured_llm: Any | None,
    plain_llm: Any,
    prompt: Any,
    render: Callable[[T], str],
    agent_name: str,
) -> str:
    """Run the structured call and render to markdown; fall back to free-text on any failure.

    ``prompt`` is whatever the underlying LLM accepts (a string for chat
    invocations, a list of message dicts for chat models that take that
    shape). The same value is forwarded to the free-text path so the
    fallback sees the same input the structured call did.
    """
    if structured_llm is not None:
        try:
            result = structured_llm.invoke(prompt)
            if result is None:
                # A thinking model can answer in plain text instead of calling
                # the tool, leaving the parser with nothing to return. Treat it
                # as a structured miss and fall back, with a clear reason.
                raise ValueError("structured output returned no parsed result")
            return render(result)
        except Exception as exc:
            logger.warning(
                "%s: structured-output invocation failed (%s); retrying once as free text",
                agent_name, exc,
            )

    response = plain_llm.invoke(prompt)
    return response.content


def invoke_structured_or_safe(
    structured_llm: Any | None,
    prompt: Any,
    render: Callable[[T], str],
    safe_fallback: Callable[[Exception], str],
    agent_name: str,
) -> str:
    """Require validated structured output for decision agents.

    One retry is allowed so the model can correct a malformed or inconsistent
    plan. Free text is never accepted at this boundary; after two failures the
    caller emits a deterministic non-executable REVIEW_REQUIRED decision.
    """
    if structured_llm is None:
        return safe_fallback(RuntimeError("provider has no structured-output support"))
    last_error: Exception = RuntimeError("structured decision failed")
    current_prompt = prompt
    for attempt in range(1, 3):
        try:
            result = structured_llm.invoke(current_prompt)
            if result is None:
                raise ValueError("structured output returned no parsed result")
            return render(result)
        except Exception as exc:
            last_error = exc
            logger.warning(
                "%s: validated structured decision attempt %d failed: %s",
                agent_name,
                attempt,
                exc,
            )
            correction = (
                "Previous structured decision was rejected by deterministic validation: "
                f"{type(exc).__name__}: {exc}. Return a corrected structured decision. "
                "Do not repeat the invalid values. Put all executable entry, stop, target, "
                "ATR, and position numbers in structured fields only; do not put calculated "
                "trade math in prose."
            )
            if isinstance(prompt, str):
                current_prompt = prompt + "\n\n" + correction
            elif isinstance(prompt, list):
                current_prompt = [*prompt, {"role": "user", "content": correction}]
    return safe_fallback(last_error)
