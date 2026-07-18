"""Runtime callback handler for LLM/tool usage statistics."""

from __future__ import annotations

import threading
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import LLMResult


CANONICAL_STATS_AGENTS = frozenset({
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
CANONICAL_STATS_TOOLS = frozenset({
    "get_balance_sheet",
    "get_cashflow",
    "get_financial_evidence",
    "get_fundamentals",
    "get_global_news",
    "get_indicators",
    "get_income_statement",
    "get_insider_transactions",
    "get_macro_indicators",
    "get_news",
    "get_prediction_markets",
    "get_social_posts",
    "get_stock_data",
    "get_stocktwits_messages",
    "get_verified_market_snapshot",
})
STATS_COST_FIELDS = ("llm_calls", "tool_calls", "tokens_in", "tokens_out")
STATS_TOOL_FIELDS = ("tool_calls", "input_chars", "output_chars", "errors")


class StatsCallbackHandler(BaseCallbackHandler):
    """Track LLM calls, tool calls, and token usage across a runtime run."""

    _AGENTS = CANONICAL_STATS_AGENTS
    _COST_FIELDS = STATS_COST_FIELDS
    _TOOL_FIELDS = STATS_TOOL_FIELDS
    _TOOLS = CANONICAL_STATS_TOOLS
    _MAX_PAYLOAD_CHARS = 50_000_000

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self.llm_calls = 0
        self.tool_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self._llm_agents: dict[UUID, str] = {}
        self._tool_runs: dict[UUID, tuple[str, str]] = {}
        self._by_agent: dict[str, dict[str, int]] = {}
        self._by_tool: dict[str, dict[str, Any]] = {}

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

    @classmethod
    def _tool_name(cls, serialized: dict[str, Any], kwargs: dict[str, Any]) -> str:
        candidates = (
            serialized.get("name") if isinstance(serialized, dict) else None,
            kwargs.get("name"),
        )
        return next(
            (
                candidate
                for candidate in candidates
                if isinstance(candidate, str) and candidate in cls._TOOLS
            ),
            "Unattributed",
        )

    @classmethod
    def _payload_chars(cls, value: Any, seen: set[int] | None = None) -> int:
        """Measure payload shape without persisting or rendering its content."""
        if value is None:
            return 0
        if isinstance(value, str):
            return min(len(value), cls._MAX_PAYLOAD_CHARS)
        if isinstance(value, bytes):
            return min(len(value), cls._MAX_PAYLOAD_CHARS)
        if isinstance(value, BaseMessage):
            return cls._payload_chars(value.content, seen)
        seen = seen if seen is not None else set()
        identity = id(value)
        if identity in seen:
            return 0
        seen.add(identity)
        if isinstance(value, dict):
            total = sum(
                cls._payload_chars(key, seen) + cls._payload_chars(item, seen)
                for key, item in value.items()
            )
        elif isinstance(value, (list, tuple, set)):
            total = sum(cls._payload_chars(item, seen) for item in value)
        else:
            try:
                total = len(str(value))
            except Exception:
                total = 0
        return min(total, cls._MAX_PAYLOAD_CHARS)

    def _tool_stats(self, tool: str, agent: str) -> tuple[dict[str, Any], dict[str, int]]:
        aggregate = self._by_tool.setdefault(
            tool,
            {
                **{field: 0 for field in self._TOOL_FIELDS},
                "by_agent": {},
            },
        )
        agent_stats = aggregate["by_agent"].setdefault(
            agent,
            {field: 0 for field in self._TOOL_FIELDS},
        )
        return aggregate, agent_stats

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
            agent = self._agent_name(kwargs)
            tool = self._tool_name(serialized, kwargs)
            input_chars = self._payload_chars(input_str)
            self.tool_calls += 1
            self._agent_stats(agent)["tool_calls"] += 1
            aggregate, agent_tool_stats = self._tool_stats(tool, agent)
            for stats in (aggregate, agent_tool_stats):
                stats["tool_calls"] += 1
                stats["input_chars"] += input_chars
            run_id = kwargs.get("run_id")
            if isinstance(run_id, UUID):
                self._tool_runs[run_id] = (tool, agent)

    def on_tool_end(self, output: Any, **kwargs: Any) -> None:
        with self._lock:
            identity = self._tool_runs.pop(kwargs.get("run_id"), None)
            if identity is None:
                return
            output_chars = self._payload_chars(output)
            aggregate, agent_tool_stats = self._tool_stats(*identity)
            aggregate["output_chars"] += output_chars
            agent_tool_stats["output_chars"] += output_chars

    def on_tool_error(self, error: BaseException, **kwargs: Any) -> None:
        with self._lock:
            identity = self._tool_runs.pop(kwargs.get("run_id"), None)
            if identity is None:
                return
            aggregate, agent_tool_stats = self._tool_stats(*identity)
            aggregate["errors"] += 1
            agent_tool_stats["errors"] += 1

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
            if self._by_tool:
                stats["by_tool"] = {
                    tool: {
                        **{
                            field: int(values[field])
                            for field in self._TOOL_FIELDS
                        },
                        "by_agent": {
                            agent: {
                                field: int(agent_values[field])
                                for field in self._TOOL_FIELDS
                            }
                            for agent, agent_values in sorted(
                                values["by_agent"].items()
                            )
                        },
                    }
                    for tool, values in sorted(self._by_tool.items())
                }
            return stats
