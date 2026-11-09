"""Per-symbol workspace layout for the optional provider integrations."""

from __future__ import annotations

import os
import json
import hashlib
import logging
import re
import tempfile
from datetime import datetime, timezone
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from functools import wraps
from io import StringIO
from pathlib import Path
from typing import Iterator

import pandas as pd

from tradingagents.dataflows.symbols import normalize_symbol, safe_ticker_component

logger = logging.getLogger(__name__)

_PERSISTED_RESULTS = {
    "get_fundamentals": ("fundamentals", "company_profile"),
    "get_balance_sheet": ("fundamentals", "balance_sheet"),
    "get_cashflow": ("fundamentals", "cashflow_statement"),
    "get_income_statement": ("fundamentals", "income_statement"),
    "get_news": ("news", "ticker_news"),
    "get_global_news": ("news", "global_news"),
    "get_insider_transactions": ("news", "insider_transactions"),
}


@dataclass(frozen=True)
class SymbolWorkspace:
    symbol: str
    root: Path

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def market_data(self) -> Path:
        return self.data / "market"

    @property
    def ohlcv_file(self) -> Path:
        return self.market_data / "ohlcv.csv"

    @property
    def ohlcv_metadata_file(self) -> Path:
        return self.market_data / "ohlcv.metadata.json"

    @property
    def fundamentals(self) -> Path:
        return self.data / "fundamentals"

    @property
    def news(self) -> Path:
        return self.data / "news"

    @property
    def runs(self) -> Path:
        return self.root / "runs"

    @property
    def memory(self) -> Path:
        return self.root / "memory"

    @property
    def config(self) -> Path:
        return self.root / "config"

    def ensure(self) -> None:
        for directory in (
            self.market_data,
            self.fundamentals,
            self.news,
            self.runs,
            self.memory,
            self.config,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def symbol_workspace(ticker: str, root: str | Path | None = None) -> SymbolWorkspace:
    """Resolve an instrument to its isolated workspace without creating it."""
    symbol = normalize_symbol(ticker)
    safe_symbol = safe_ticker_component(symbol)
    configured_root = root or os.getenv("TRADINGAGENTS_WORKSPACES_DIR")
    base = (
        Path(configured_root).expanduser().resolve()
        if configured_root
        else Path.home() / ".tradingagents" / "workspaces"
    )
    return SymbolWorkspace(symbol=symbol, root=base / safe_symbol)


def config_for_workspace(config: dict, workspace: SymbolWorkspace) -> dict:
    """Bind mutable TradingAgents outputs and cache roots to one symbol."""
    workspace.ensure()
    result = deepcopy(config)
    result["results_dir"] = str(workspace.runs)
    # Checkpoints are kept below data/checkpoints; the provider adapters below
    # split actual market and financial caches into their semantic directories.
    result["data_cache_dir"] = str(workspace.data)
    result["memory_log_path"] = str(workspace.memory / "trading_memory.md")
    return result


def _request_record(args: tuple, kwargs: dict) -> dict:
    """Keep cache keys and manifests stable across identical provider calls."""
    return {"args": list(args), "kwargs": kwargs}


def _persist_provider_result(
    workspace: SymbolWorkspace,
    method: str,
    provider: str,
    args: tuple,
    kwargs: dict,
    payload: object,
) -> None:
    """Persist successful fundamentals/news responses with source metadata."""
    if not isinstance(payload, str) or not payload.strip():
        return
    if payload.startswith(("DATA_UNAVAILABLE:", "NO_DATA_AVAILABLE:")):
        return
    category, stem = _PERSISTED_RESULTS[method]
    request = _request_record(args, kwargs)
    request_json = json.dumps(request, ensure_ascii=False, sort_keys=True, default=str)
    fingerprint = hashlib.sha256(request_json.encode("utf-8")).hexdigest()[:12]
    dates = list(dict.fromkeys(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", request_json)))[:2]
    date_part = "_".join(dates)
    filename = f"{stem}{'_' + date_part if date_part else ''}_{fingerprint}.json"
    directory = workspace.fundamentals if category == "fundamentals" else workspace.news
    directory.mkdir(parents=True, exist_ok=True)
    document = {
        "symbol": workspace.symbol,
        "method": method,
        "provider": provider,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "request": request,
        "content_type": "text/plain; charset=utf-8",
        "content": payload,
    }
    with tempfile.NamedTemporaryFile(
        "w", dir=directory, suffix=".tmp", delete=False, encoding="utf-8"
    ) as stream:
        temp_path = Path(stream.name)
    try:
        temp_path.write_text(json.dumps(document, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        temp_path.replace(directory / filename)
    finally:
        temp_path.unlink(missing_ok=True)


def _flatten_existing_run_logs(workspace: SymbolWorkspace) -> None:
    """Move older nested core run logs into the workspace's direct runs folder."""
    ticker = safe_ticker_component(workspace.symbol)
    nested = workspace.runs / ticker / "TradingAgentsStrategy_logs"
    if not nested.is_dir():
        return
    target = workspace.runs / "TradingAgentsStrategy_logs"
    try:
        for source in nested.glob("full_states_log_*.json"):
            destination = target / source.name
            if destination.exists():
                # Preserve both files if an earlier flattened run already has
                # a report for the same date.
                stamp = datetime.fromtimestamp(source.stat().st_mtime).strftime("%Y%m%dT%H%M%S")
                destination = target / f"{source.stem}_{stamp}{source.suffix}"
            target.mkdir(parents=True, exist_ok=True)
            source.replace(destination)
        nested.rmdir()
        (workspace.runs / ticker).rmdir()
    except OSError as exc:
        logger.warning("Could not fully flatten prior run logs for %s: %s", workspace.symbol, exc)


@contextmanager
def workspace_result_paths(workspace: SymbolWorkspace) -> Iterator[None]:
    """Keep core reports directly under this already symbol-scoped workspace."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    original = TradingAgentsGraph._log_state
    _flatten_existing_run_logs(workspace)

    def write_flattened(self, trade_date, final_state):
        result = original(self, trade_date, final_state)
        ticker = safe_ticker_component(final_state["company_of_interest"])
        run_root = Path(self.config["results_dir"])
        nested = run_root / ticker / "TradingAgentsStrategy_logs"
        source = nested / f"full_states_log_{trade_date}.json"
        target_dir = run_root / "TradingAgentsStrategy_logs"
        target = target_dir / source.name
        try:
            if source.exists():
                target_dir.mkdir(parents=True, exist_ok=True)
                source.replace(target)
                nested.rmdir()
                (run_root / ticker).rmdir()
        except OSError as exc:
            # Preserve the core writer's successful result if relocation fails.
            logger.warning("Could not flatten the latest run log for %s: %s", ticker, exc)
        return result

    TradingAgentsGraph._log_state = write_flattened
    try:
        yield
    finally:
        TradingAgentsGraph._log_state = original


@contextmanager
def workspace_cache_paths(workspace: SymbolWorkspace) -> Iterator[None]:
    """Keep one provider-neutral OHLCV file and scope SEC caches to the symbol."""
    from tradingagents.dataflows.router import VENDOR_METHODS
    import tradingagents.dataflows.vendors.sec_edgar as sec_edgar
    from tradingagents.dataflows.vendors.yahoo import ohlcv as yahoo_ohlcv

    methods_to_wrap = {"get_stock_data", *_PERSISTED_RESULTS}
    previous_vendor_methods = {
        method: VENDOR_METHODS[method].copy() for method in methods_to_wrap
    }
    previous_yahoo_get_config = yahoo_ohlcv.get_config
    previous_sec_get_config = sec_edgar.get_config

    def scoped_config(get_config, cache_directory: Path):
        def read_config():
            config = get_config()
            config["data_cache_dir"] = str(cache_directory)
            return config

        return read_config

    yahoo_ohlcv.get_config = scoped_config(previous_yahoo_get_config, workspace.market_data)
    sec_edgar.get_config = scoped_config(previous_sec_get_config, workspace.fundamentals)

    def persist_ohlcv(provider, implementation):
        @wraps(implementation)
        def wrapped(symbol, start_date, end_date, *args, **kwargs):
            payload = implementation(symbol, start_date, end_date, *args, **kwargs)
            if not isinstance(payload, str) or payload.startswith(("DATA_UNAVAILABLE:", "NO_DATA_AVAILABLE:")):
                return payload
            try:
                incoming = pd.read_csv(StringIO(payload), comment="#")
                if "Date" not in incoming.columns and len(incoming.columns) >= 7:
                    incoming = incoming.rename(columns={incoming.columns[0]: "Date"})
                required = ["Date", "Open", "High", "Low", "Close", "Volume"]
                if not set(required).issubset(incoming.columns):
                    return payload
                incoming = incoming.loc[:, required]
                incoming["Date"] = pd.to_datetime(incoming["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
                for column in required[1:]:
                    incoming[column] = pd.to_numeric(incoming[column], errors="coerce")
                incoming = incoming.dropna(subset=["Date", "Close"])
                if incoming.empty:
                    return payload
                canonical = workspace.symbol
                existing = pd.DataFrame(columns=required)
                if workspace.ohlcv_file.exists():
                    existing = pd.read_csv(workspace.ohlcv_file)
                    existing = existing.loc[:, required]
                merged = pd.concat([existing, incoming], ignore_index=True)
                merged["Date"] = pd.to_datetime(merged["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
                merged = merged.dropna(subset=["Date", "Close"]).drop_duplicates("Date", keep="last").sort_values("Date")
                workspace.market_data.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile("w", dir=workspace.market_data, suffix=".tmp", delete=False, encoding="utf-8") as stream:
                    temp_path = Path(stream.name)
                try:
                    merged.to_csv(temp_path, index=False)
                    temp_path.replace(workspace.ohlcv_file)
                finally:
                    temp_path.unlink(missing_ok=True)
                previous_metadata = {}
                if workspace.ohlcv_metadata_file.exists():
                    previous_metadata = json.loads(workspace.ohlcv_metadata_file.read_text(encoding="utf-8"))
                providers = set(previous_metadata.get("providers", []))
                providers.add(provider)
                metadata = {
                    "symbol": canonical,
                    "schema": "Date,Open,High,Low,Close,Volume",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "latest_provider": provider,
                    "row_count": int(len(merged)),
                    "providers": sorted(providers),
                }
                workspace.ohlcv_metadata_file.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
            except (OSError, ValueError, pd.errors.ParserError):
                # Cache persistence is best-effort; never break a successful data call.
                return payload
            return payload
        return wrapped

    def persist_result(method, provider, implementation):
        @wraps(implementation)
        def wrapped(*args, **kwargs):
            payload = implementation(*args, **kwargs)
            try:
                _persist_provider_result(workspace, method, provider, args, kwargs, payload)
            except (OSError, TypeError, ValueError) as exc:
                # Persistence is best-effort and must not turn successful data
                # retrieval into a failed tool call.
                logger.warning("Could not persist %s result from %s: %s", method, provider, exc)
            return payload
        return wrapped

    patched_vendor_methods = {}
    for method, vendors in previous_vendor_methods.items():
        if method == "get_stock_data":
            patched_vendor_methods[method] = {
                name: persist_ohlcv(name, implementation)
                for name, implementation in vendors.items()
            }
        else:
            patched_vendor_methods[method] = {
                name: persist_result(method, name, implementation)
                for name, implementation in vendors.items()
            }
    for method, vendors in patched_vendor_methods.items():
        VENDOR_METHODS[method] = vendors
    # Direct Yahoo indicator retrieval also depends on load_ohlcv. Keep its
    # legacy internal cache path inside the workspace; all router OHLCV calls
    # additionally update the canonical provider-neutral file above.
    try:
        yield
    finally:
        for method, vendors in previous_vendor_methods.items():
            VENDOR_METHODS[method].clear()
            VENDOR_METHODS[method].update(vendors)
        yahoo_ohlcv.get_config = previous_yahoo_get_config
        sec_edgar.get_config = previous_sec_get_config
