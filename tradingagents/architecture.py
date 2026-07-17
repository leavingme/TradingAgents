"""Version label for longitudinal agent-architecture evaluation."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any


# Deliberately server-owned. API/browser callers cannot label their own run as
# a challenger and thereby contaminate architecture comparisons.
AGENT_ARCHITECTURE_VERSION = os.environ.get(
    "TRADINGAGENTS_ARCHITECTURE_VERSION",
    "2026-07-17.2",
)


def build_architecture_manifest(
    *,
    version: str,
    selected_analysts: tuple[str, ...] | list[str],
    research_depth: int | None,
    llm_provider: str | None,
    quick_think_llm: str | None,
    deep_think_llm: str | None,
    longitudinal_context_mode: str = "research_and_portfolio",
) -> dict[str, Any]:
    """Return the canonical agent topology/model manifest for one run."""
    return {
        "schema": "tradingagents/agent-architecture-manifest/v1",
        "version": version,
        "selected_analysts": sorted(str(item).lower() for item in selected_analysts),
        "research_depth": research_depth,
        "llm_provider": llm_provider.lower() if llm_provider else None,
        "quick_think_llm": quick_think_llm,
        "deep_think_llm": deep_think_llm,
        "longitudinal_context_mode": longitudinal_context_mode,
    }


def architecture_fingerprint(manifest: dict[str, Any]) -> str:
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
