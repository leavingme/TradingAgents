"""Server-side persistence for Web runtime and data-vendor preferences."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any

from tradingagents.default_config import DEFAULT_CONFIG


SETTING_KEYS = {
    "research_depth",
    "llm_provider",
    "quick_think_llm",
    "deep_think_llm",
    "backend_url",
    "output_language",
    "google_thinking_level",
    "openai_reasoning_effort",
    "anthropic_effort",
}

ALLOWED_VENDORS = {
    "core_stock_apis": ["longbridge_mcp", "longbridge", "westock", "alpha_vantage"],
    "technical_indicators": ["longbridge_mcp", "longbridge", "westock", "alpha_vantage"],
    "fundamental_data": ["longbridge_mcp", "longbridge", "westock", "alpha_vantage"],
    "news_data": ["longbridge_mcp", "longbridge", "westock", "duckduckgo", "alpha_vantage"],
    "social_data": ["bird", "reddit"],
    "macro_data": ["fred"],
    "prediction_markets": ["polymarket"],
}

LEGACY_NEWS_DEFAULT = ("westock", "duckduckgo", "alpha_vantage")


def _default_path() -> Path:
    override = os.environ.get("TRADINGAGENTS_WEB_CONFIG_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".tradingagents" / "web_config.json"


def _default_vendor_rows() -> dict[str, list[dict[str, Any]]]:
    configured = DEFAULT_CONFIG.get("data_vendors", {})
    result = {}
    for category, allowed in ALLOWED_VENDORS.items():
        enabled = [item.strip() for item in configured.get(category, "").split(",") if item.strip()]
        result[category] = [
            {"id": vendor, "enabled": vendor in enabled}
            for vendor in [*enabled, *[item for item in allowed if item not in enabled]]
            if vendor in allowed
        ]
    return result


def _normalize_vendor_rows(
    payload: Any, *, migrate_legacy_defaults: bool = False
) -> dict[str, list[dict[str, Any]]]:
    source = payload if isinstance(payload, dict) else {}
    defaults = _default_vendor_rows()
    result = {}
    for category, allowed in ALLOWED_VENDORS.items():
        rows = source.get(category)
        legacy_news_ids = (
            tuple(row.get("id") for row in rows if isinstance(row, dict))
            if isinstance(rows, list)
            else ()
        )
        if (
            migrate_legacy_defaults
            and category == "news_data"
            and legacy_news_ids == LEGACY_NEWS_DEFAULT
            and all(row.get("enabled") is not False for row in rows if isinstance(row, dict))
        ):
            rows = defaults[category]
        if not isinstance(rows, list):
            result[category] = defaults[category]
            continue
        seen = set()
        normalized = []
        for row in rows:
            vendor = row.get("id") if isinstance(row, dict) else None
            if vendor not in allowed or vendor in seen:
                continue
            normalized.append({"id": vendor, "enabled": row.get("enabled") is not False})
            seen.add(vendor)
        normalized.extend({"id": vendor, "enabled": False} for vendor in allowed if vendor not in seen)
        result[category] = normalized
    return result


class WebConfigStore:
    def __init__(self, path: Path | None = None):
        self.path = path or _default_path()
        self._lock = RLock()

    def load(self) -> dict[str, Any]:
        with self._lock:
            stored: dict[str, Any] = {}
            try:
                stored = json.loads(self.path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                pass
            settings = stored.get("settings") if isinstance(stored.get("settings"), dict) else {}
            return {
                "settings": {key: deepcopy(value) for key, value in settings.items() if key in SETTING_KEYS},
                "providers": _normalize_vendor_rows(
                    stored.get("providers"), migrate_legacy_defaults=True
                ),
                "persisted": self.path.exists(),
            }

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            current = self.load()
            settings = payload.get("settings")
            providers = payload.get("providers")
            if isinstance(settings, dict):
                current["settings"] = {
                    key: deepcopy(value) for key, value in settings.items() if key in SETTING_KEYS
                }
            if isinstance(providers, dict):
                current["providers"] = _normalize_vendor_rows(providers)
            document = {"settings": current["settings"], "providers": current["providers"]}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)
            return {**deepcopy(document), "persisted": True}

    def reset(self) -> dict[str, Any]:
        with self._lock:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            return self.load()


web_config_store = WebConfigStore()
