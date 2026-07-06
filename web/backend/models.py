"""Pydantic models for the minimal TradingAgents Web API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RunCreateRequest(BaseModel):
    ticker: str = Field(min_length=1)
    analysis_date: str
    asset_type: str = "stock"
    selected_analysts: list[str] = Field(
        default_factory=lambda: ["market", "social", "news", "fundamentals"]
    )
    llm_provider: str | None = None
    quick_think_llm: str | None = None
    deep_think_llm: str | None = None
    research_depth: int | None = None
    backend_url: str | None = None
    output_language: str | None = None
    checkpoint_enabled: bool | None = None
    results_dir: str | None = None
    report_dir: str | None = None
    config_overrides: dict[str, Any] = Field(default_factory=dict)


RunStatus = Literal["pending", "running", "completed", "failed", "cancelled"]


class RunRecordResponse(BaseModel):
    run_id: str
    status: RunStatus
    ticker: str
    analysis_date: str
    asset_type: str
    selected_analysts: list[str]
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    report_path: str | None = None
    error: str | None = None
    event_count: int = 0
