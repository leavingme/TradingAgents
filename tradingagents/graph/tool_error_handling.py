"""Narrow recovery policy for model-generated tool argument errors."""

from __future__ import annotations

from collections.abc import Callable

from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest, ToolInvocationError


_CORRECTION_MARKER = "[tool-argument-correction]"


def recover_invalid_tool_arguments(
    request: ToolCallRequest,
    execute: Callable[[ToolCallRequest], ToolMessage],
) -> ToolMessage:
    """Return one invalid-argument error to the LLM, then fail on repetition.

    Only ``ToolInvocationError`` is recoverable here. Exceptions raised by the
    tool implementation (vendor authentication, transport, validation, or
    no-data failures) deliberately continue to propagate through the graph.
    """
    try:
        return execute(request)
    except ToolInvocationError as exc:
        messages = (
            request.state.get("messages", [])
            if isinstance(request.state, dict)
            else []
        )
        already_corrected = any(
            isinstance(message, ToolMessage)
            and message.status == "error"
            and _CORRECTION_MARKER in str(message.content)
            for message in messages
        )
        if already_corrected:
            raise

        return ToolMessage(
            content=(
                f"{_CORRECTION_MARKER} The tool arguments did not match the "
                "required schema. Correct the arguments and retry this tool once. "
                "Use the ticker and trading date from the conversation; do not "
                f"invent missing semantic parameters.\n{exc.message}"
            ),
            name=request.tool_call["name"],
            tool_call_id=request.tool_call["id"],
            status="error",
        )
