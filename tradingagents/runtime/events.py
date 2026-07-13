"""Runtime request/result/event models for headless analysis runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

EventType = Literal[
    "run_started",
    "message",
    "tool_call",
    "agent_status",
    "report_section",
    "stats",
    "run_completed",
    "run_cancelled",
    "error",
]


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AnalysisEvent:
    """A structured event emitted by a headless analysis run."""

    type: EventType
    run_id: str
    timestamp: str = field(default_factory=utc_timestamp)
    agent: str | None = None
    content: str | dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "agent": self.agent,
            "content": self.content,
        }


@dataclass(frozen=True)
class AnalysisRequest:
    """Input needed to execute an analysis without a terminal UI."""

    ticker: str
    analysis_date: str
    asset_type: str = "stock"
    selected_analysts: tuple[str, ...] = ("market", "social", "news", "fundamentals")
    llm_provider: str | None = None
    quick_think_llm: str | None = None
    deep_think_llm: str | None = None
    research_depth: int | None = None
    backend_url: str | None = None
    output_language: str | None = None
    checkpoint_enabled: bool | None = None
    results_dir: str | Path | None = None
    report_dir: str | Path | None = None
    analysis_mode: Literal["live", "point_in_time"] = "live"
    information_cutoff: str | None = None
    # Provider-specific reasoning/thinking configuration
    google_thinking_level: str | None = None
    openai_reasoning_effort: str | None = None
    anthropic_effort: str | None = None
    run_id: str = field(default_factory=lambda: uuid4().hex)
    debug: bool = False
    config_overrides: dict[str, Any] = field(default_factory=dict)
    callbacks: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        from .audit_context import validate_temporal_context

        validate_temporal_context(
            self.analysis_date, self.analysis_mode, self.information_cutoff
        )


@dataclass(frozen=True)
class AnalysisResult:
    """Final result returned by non-streaming callers."""

    run_id: str
    final_state: dict[str, Any]
    decision: Any
    decision_status: Literal["validated", "review_required", "unavailable"]
    report_path: Path | None
    events: tuple[AnalysisEvent, ...]
