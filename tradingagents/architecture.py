"""Version label for longitudinal agent-architecture evaluation."""

from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from math import isfinite
from pathlib import Path
from typing import Any


# Deliberately server-owned. API/browser callers cannot label their own run as
# a challenger and thereby contaminate architecture comparisons.
AGENT_ARCHITECTURE_VERSION = os.environ.get(
    "TRADINGAGENTS_ARCHITECTURE_VERSION",
    "2026-07-17.2",
)

_DECISION_IMPLEMENTATION_GLOBS = (
    "architecture.py",
    "default_config.py",
    "agents/**/*.py",
    "dataflows/**/*.py",
    "graph/**/*.py",
    "llm_clients/**/*.py",
    "runtime/analysis_runner.py",
    "runtime/audit_context.py",
    "runtime/config_builder.py",
    "runtime/events.py",
    "runtime/history.py",
)
IMPLEMENTATION_DIGEST_SCOPE = tuple(
    f"tradingagents/{pattern}" for pattern in _DECISION_IMPLEMENTATION_GLOBS
)
ARCHITECTURE_EXPERIMENT_INPUT_SCHEMA = (
    "tradingagents/research-manager-pre-context-input/v1"
)
_SCALAR_DECISION_CONFIG_KEYS = (
    "max_debate_rounds",
    "max_risk_discuss_rounds",
    "output_language",
    "google_thinking_level",
    "openai_reasoning_effort",
    "anthropic_effort",
    "temperature",
    "max_recur_limit",
    "benchmark_ticker",
    "news_article_limit",
    "global_news_article_limit",
    "global_news_lookback_days",
)
_MAPPING_DECISION_CONFIG_KEYS = (
    "data_vendors",
    "tool_vendors",
    "trade_risk_policy",
    "benchmark_map",
)


def _digest_python_sources(source_root: Path) -> str:
    root = source_root.resolve()
    sources = sorted({
        path
        for pattern in _DECISION_IMPLEMENTATION_GLOBS
        for path in root.glob(pattern)
        if path.is_file() and "__pycache__" not in path.parts
    })
    if not sources:
        raise RuntimeError(f"no Python implementation sources found under {root}")
    digest = hashlib.sha256()
    for path in sources:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


@lru_cache(maxsize=1)
def _default_implementation_digest() -> str:
    return _digest_python_sources(Path(__file__).resolve().parent)


def architecture_implementation_digest(source_root: Path | None = None) -> str:
    """Hash the effective TradingAgents Python implementation without paths or secrets."""
    if source_root is None:
        return _default_implementation_digest()
    return _digest_python_sources(source_root)


def _safe_scalar(value: Any) -> bool:
    if isinstance(value, (str, bool, int)):
        return True
    return isinstance(value, float) and isfinite(value)


def _safe_decision_config(config: dict[str, Any] | None) -> dict[str, Any]:
    if not config:
        return {}
    output = {
        key: config.get(key)
        for key in _SCALAR_DECISION_CONFIG_KEYS
        if _safe_scalar(config.get(key))
    }
    for key in _MAPPING_DECISION_CONFIG_KEYS:
        value = config.get(key)
        if not isinstance(value, dict):
            continue
        output[key] = {
            str(item_key): item_value
            for item_key, item_value in sorted(value.items(), key=lambda item: str(item[0]))
            if _safe_scalar(item_value)
        }
    queries = config.get("global_news_queries")
    if isinstance(queries, (list, tuple)):
        output["global_news_queries"] = [
            item for item in queries if isinstance(item, str)
        ]
    output["custom_backend_configured"] = bool(config.get("backend_url"))
    return output


def build_architecture_manifest(
    *,
    version: str,
    selected_analysts: tuple[str, ...] | list[str],
    research_depth: int | None,
    llm_provider: str | None,
    quick_think_llm: str | None,
    deep_think_llm: str | None,
    longitudinal_context_mode: str = "research_and_portfolio",
    effective_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the canonical agent topology/model manifest for one run."""
    from tradingagents.evaluation import longitudinal_evaluation_policy

    return {
        "schema": "tradingagents/agent-architecture-manifest/v4",
        "version": version,
        "implementation_digest": architecture_implementation_digest(),
        "implementation_digest_scope": list(IMPLEMENTATION_DIGEST_SCOPE),
        "selected_analysts": sorted(str(item).lower() for item in selected_analysts),
        "research_depth": research_depth,
        "llm_provider": llm_provider.lower() if llm_provider else None,
        "quick_think_llm": quick_think_llm,
        "deep_think_llm": deep_think_llm,
        "longitudinal_context_mode": longitudinal_context_mode,
        "longitudinal_evaluation_policy": longitudinal_evaluation_policy(),
        "decision_config": _safe_decision_config(effective_config),
    }


def architecture_fingerprint(manifest: dict[str, Any]) -> str:
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def architecture_experiment_input_identity(state: dict[str, Any]) -> dict[str, Any]:
    """Fingerprint the state immediately before the supported RM context branch.

    The current shadow template changes only Research Manager longitudinal-context
    injection. Its treatment fields are intentionally absent from this manifest;
    upstream instrument context and debate history must otherwise be identical for
    a pair to support causal attribution.
    """
    debate = state.get("investment_debate_state")
    debate_history = debate.get("history") if isinstance(debate, dict) else None
    instrument_context = state.get("instrument_context")
    manifest = {
        "schema": ARCHITECTURE_EXPERIMENT_INPUT_SCHEMA,
        "ticker": state.get("company_of_interest"),
        "analysis_date": state.get("trade_date"),
        "asset_type": state.get("asset_type"),
        "instrument_context": instrument_context,
        "investment_debate_history": debate_history,
    }
    complete = bool(instrument_context) and bool(debate_history)
    try:
        canonical = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        # Unsupported objects must not acquire potentially unstable repr-based
        # identities. Retain an auditable but deliberately incomplete marker.
        complete = False
        canonical = json.dumps({
            "schema": ARCHITECTURE_EXPERIMENT_INPUT_SCHEMA,
            "ticker": state.get("company_of_interest"),
            "analysis_date": state.get("trade_date"),
            "asset_type": state.get("asset_type"),
            "serialization_error": True,
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "schema": ARCHITECTURE_EXPERIMENT_INPUT_SCHEMA,
        "fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "complete": complete,
    }
