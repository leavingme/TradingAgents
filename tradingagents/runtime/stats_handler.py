"""Runtime callback handler for LLM/tool usage statistics."""

from __future__ import annotations

import threading
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.outputs import LLMResult


class StatsCallbackHandler(BaseCallbackHandler):
    """Track LLM calls, tool calls, and token usage across a runtime run."""

    _AGENTS = frozenset({
        "Market Analyst",
        "Sentiment Analyst",
        "News Analyst",
        "Fundamentals Analyst",
        "Bull Researcher",
        "Bear Researcher",
        "Research Manager",
        "Trader",
        "Aggressive Analyst",
        "Conservative Analyst",
        "Neutral Analyst",
        "Portfolio Manager",
    })
    _COST_FIELDS = ("llm_calls", "tool_calls", "tokens_in", "tokens_out")

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self.llm_calls = 0
        self.tool_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self._llm_agents: dict[UUID, str] = {}
        self._by_agent: dict[str, dict[str, int]] = {}

    @classmethod
    def _agent_name(cls, kwargs: dict[str, Any]) -> str:
        metadata = kwargs.get("metadata")
        candidate = metadata.get("langgraph_node") if isinstance(metadata, dict) else None
        return candidate if isinstance(candidate, str) and candidate in cls._AGENTS else "Unattributed"

    @staticmethod
    def _token_count(value: Any) -> int:
        try:
            count = int(value or 0)
        except (TypeError, ValueError):
            return 0
        return max(count, 0)

    def _agent_stats(self, agent: str) -> dict[str, int]:
        return self._by_agent.setdefault(
            agent,
            {field: 0 for field in self._COST_FIELDS},
        )

    def _record_llm_start(self, kwargs: dict[str, Any]) -> None:
        agent = self._agent_name(kwargs)
        self.llm_calls += 1
        self._agent_stats(agent)["llm_calls"] += 1
        run_id = kwargs.get("run_id")
        if isinstance(run_id, UUID):
            self._llm_agents[run_id] = agent

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        **kwargs: Any,
    ) -> None:
        with self._lock:
            self._record_llm_start(kwargs)

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        **kwargs: Any,
    ) -> None:
        with self._lock:
            self._record_llm_start(kwargs)

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        run_id = kwargs.get("run_id")
        try:
            generation = response.generations[0][0]
        except (IndexError, TypeError):
            with self._lock:
                self._llm_agents.pop(run_id, None)
            return

        usage_metadata = None
        if hasattr(generation, "message"):
            message = generation.message
            if isinstance(message, AIMessage) and hasattr(message, "usage_metadata"):
                usage_metadata = message.usage_metadata

        with self._lock:
            agent = self._llm_agents.pop(run_id, "Unattributed")
            if usage_metadata:
                tokens_in = self._token_count(usage_metadata.get("input_tokens"))
                tokens_out = self._token_count(usage_metadata.get("output_tokens"))
                self.tokens_in += tokens_in
                self.tokens_out += tokens_out
                agent_stats = self._agent_stats(agent)
                agent_stats["tokens_in"] += tokens_in
                agent_stats["tokens_out"] += tokens_out

    def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        with self._lock:
            self._llm_agents.pop(kwargs.get("run_id"), None)

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        with self._lock:
            self.tool_calls += 1
            self._agent_stats(self._agent_name(kwargs))["tool_calls"] += 1

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            stats: dict[str, Any] = {
                "llm_calls": self.llm_calls,
                "tool_calls": self.tool_calls,
                "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out,
            }
            if self._by_agent:
                stats["by_agent"] = {
                    agent: dict(values)
                    for agent, values in sorted(self._by_agent.items())
                }
            return stats
