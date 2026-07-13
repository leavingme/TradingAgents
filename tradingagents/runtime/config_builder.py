"""Build TradingAgents configuration for headless analysis runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tradingagents.default_config import DEFAULT_CONFIG

from .events import AnalysisRequest


def build_runtime_config(request: AnalysisRequest) -> dict[str, Any]:
    """Return a graph config from a runtime request.

    Only request fields explicitly set by the caller override DEFAULT_CONFIG.
    This keeps environment/default handling aligned with the existing CLI path.
    """
    config = DEFAULT_CONFIG.copy()

    if request.research_depth is not None:
        config["max_debate_rounds"] = request.research_depth
        config["max_risk_discuss_rounds"] = request.research_depth
    if request.quick_think_llm:
        config["quick_think_llm"] = request.quick_think_llm
    if request.deep_think_llm:
        config["deep_think_llm"] = request.deep_think_llm
    if request.llm_provider:
        config["llm_provider"] = request.llm_provider.lower()
    if request.backend_url is not None:
        config["backend_url"] = request.backend_url
    if request.output_language:
        config["output_language"] = request.output_language
    if request.checkpoint_enabled is not None:
        config["checkpoint_enabled"] = request.checkpoint_enabled
    if request.results_dir is not None:
        config["results_dir"] = str(Path(request.results_dir))
    if request.google_thinking_level is not None:
        config["google_thinking_level"] = request.google_thinking_level
    if request.openai_reasoning_effort is not None:
        config["openai_reasoning_effort"] = request.openai_reasoning_effort
    if request.anthropic_effort is not None:
        config["anthropic_effort"] = request.anthropic_effort

    # Merge config_overrides (1-level deep for dict-valued keys like data_vendors)
    protected_keys = {"trade_risk_policy"}
    forbidden = protected_keys.intersection(request.config_overrides)
    if forbidden:
        raise ValueError(
            "Per-run overrides cannot modify server-owned settings: "
            + ", ".join(sorted(forbidden))
        )
    for key, val in request.config_overrides.items():
        if isinstance(val, dict) and isinstance(config.get(key), dict):
            config[key] = config[key].copy()
            config[key].update(val)
        else:
            config[key] = val
    return config
