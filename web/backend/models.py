"""Pydantic models for the minimal TradingAgents Web API."""

from __future__ import annotations

import os
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients.openai_client import OPENAI_COMPATIBLE_PROVIDERS


def _normalise_backend_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("backend_url must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("backend_url cannot contain credentials, query, or fragment")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("non-loopback backend_url must use HTTPS")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))


def allowed_backend_urls() -> set[str]:
    """Server-owned endpoint allowlist; API callers cannot extend it."""
    urls = {
        "https://api.openai.com/v1",
        "https://api.anthropic.com",
        "https://generativelanguage.googleapis.com",
    }
    for spec in OPENAI_COMPATIBLE_PROVIDERS.values():
        if spec.base_url:
            urls.add(spec.base_url)
        if spec.base_url_env and os.environ.get(spec.base_url_env):
            urls.add(os.environ[spec.base_url_env])
    configured = os.environ.get("TRADINGAGENTS_ALLOWED_BACKEND_URLS", "")
    urls.update(item.strip() for item in configured.split(",") if item.strip())
    for env_name in ("TRADINGAGENTS_LLM_BACKEND_URL", "OPENAI_BASE_URL"):
        if os.environ.get(env_name):
            urls.add(os.environ[env_name])
    return {_normalise_backend_url(url) for url in urls}


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1)
    analysis_date: str
    asset_type: str = "stock"
    selected_analysts: list[str] = Field(
        default_factory=lambda: ["market", "social", "news", "fundamentals"]
    )
    llm_provider: str | None = "minimax-cn"
    quick_think_llm: str | None = "MiniMax-M3"
    deep_think_llm: str | None = "MiniMax-M3"
    research_depth: int | None = None
    backend_url: str | None = None
    output_language: str | None = "Chinese"
    checkpoint_enabled: bool | None = None
    google_thinking_level: str | None = None
    openai_reasoning_effort: str | None = None
    anthropic_effort: str | None = None
    config_overrides: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_web_trust_boundary(self):
        if self.backend_url is not None:
            normalized = _normalise_backend_url(self.backend_url)
            if normalized not in allowed_backend_urls():
                raise ValueError("backend_url is not present in the server allowlist")
            self.backend_url = normalized

        unknown_top = set(self.config_overrides) - {"data_vendors"}
        if unknown_top:
            raise ValueError(
                "config_overrides contains non-Web settings: "
                + ", ".join(sorted(unknown_top))
            )
        vendors = self.config_overrides.get("data_vendors", {})
        if not isinstance(vendors, dict):
            raise ValueError("config_overrides.data_vendors must be an object")
        allowed_categories = set(DEFAULT_CONFIG.get("data_vendors", {}))
        unknown_categories = set(vendors) - allowed_categories
        if unknown_categories:
            raise ValueError(
                "unknown data vendor categories: "
                + ", ".join(sorted(unknown_categories))
            )
        if any(not isinstance(value, str) for value in vendors.values()):
            raise ValueError("data vendor priorities must be comma-separated strings")
        return self


RunStatus = Literal[
    "pending", "running", "completed", "review_required", "unavailable", "failed", "cancelled"
]


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
    decision_status: Literal["validated", "review_required", "unavailable"] = "unavailable"
    data_status: Literal["not_observed", "available", "degraded", "unavailable"] = "not_observed"
    vendor_summary: dict[str, Any] = Field(default_factory=dict)
    event_count: int = 0
