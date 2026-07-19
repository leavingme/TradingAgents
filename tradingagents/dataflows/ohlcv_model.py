"""Unified structured OHLCV domain model used between vendors and routing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd


@dataclass(frozen=True)
class OHLCVBar:
    trading_date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    raw_timestamp: str | None = None


@dataclass(frozen=True)
class OHLCVBatch:
    symbol: str
    vendor: str
    adapter_version: str
    timezone_semantics: str
    bars: tuple[OHLCVBar, ...]
    batch_id: str
    fetched_at: str


def batch_from_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    vendor: str,
    adapter_version: str,
    timezone_semantics: str,
    raw_timestamps: list[str | None] | None = None,
) -> OHLCVBatch:
    """Convert an adapter-normalized frame into the unified model."""
    required = ("Date", "Open", "High", "Low", "Close", "Volume")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"OHLCV adapter missing columns: {', '.join(missing)}")
    bars = []
    for position, row in enumerate(frame.itertuples(index=False)):
        values = row._asdict()
        date = pd.Timestamp(values["Date"])
        bars.append(OHLCVBar(
            trading_date=date.strftime("%Y-%m-%d"),
            open=float(values["Open"]), high=float(values["High"]),
            low=float(values["Low"]), close=float(values["Close"]),
            volume=float(values["Volume"]),
            raw_timestamp=(raw_timestamps[position] if raw_timestamps else None),
        ))
    return OHLCVBatch(
        symbol=symbol,
        vendor=vendor,
        adapter_version=adapter_version,
        timezone_semantics=timezone_semantics,
        bars=tuple(bars),
        batch_id=uuid4().hex,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )


def batch_to_frame(batch: OHLCVBatch) -> pd.DataFrame:
    if not isinstance(batch, OHLCVBatch):
        raise TypeError("OHLCV cache accepts only OHLCVBatch")
    return pd.DataFrame([{
        "Date": bar.trading_date, "Open": bar.open, "High": bar.high,
        "Low": bar.low, "Close": bar.close, "Volume": bar.volume,
    } for bar in batch.bars])


def append_ohlcv_audit(cache_dir: str, cache_key: str, batch: OHLCVBatch) -> None:
    """Append provenance without putting raw vendor payloads in the cache CSV."""
    path = Path(cache_dir) / "ohlcv_audit.jsonl"
    record: dict[str, Any] = {
        "cache_key": cache_key,
        "symbol": batch.symbol,
        "vendor": batch.vendor,
        "adapter_version": batch.adapter_version,
        "timezone_semantics": batch.timezone_semantics,
        "batch_id": batch.batch_id,
        "fetched_at": batch.fetched_at,
        "bar_count": len(batch.bars),
        "first_trading_date": batch.bars[0].trading_date if batch.bars else None,
        "last_trading_date": batch.bars[-1].trading_date if batch.bars else None,
        "trading_dates": [bar.trading_date for bar in batch.bars],
        "raw_timestamps": [bar.raw_timestamp for bar in batch.bars],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def resolve_ohlcv_source_id(
    cache_dir: str,
    cache_key: str,
    trading_date: str,
) -> str | None:
    """Resolve one cached bar to an exact audited vendor batch."""
    provenance = resolve_ohlcv_provenance(
        cache_dir,
        cache_key,
        (trading_date,),
    ).get(trading_date)
    if provenance is None:
        return None
    return (
        f"ohlcv:{provenance['vendor']}:{provenance['batch_id']}:"
        f"{trading_date}"
    )


def resolve_ohlcv_provenance(
    cache_dir: str,
    cache_key: str,
    trading_dates: tuple[str, ...] | list[str],
) -> dict[str, dict[str, str]]:
    """Resolve cached rows to their newest exact vendor batches in one scan."""
    unresolved = {
        str(value) for value in trading_dates if str(value).strip()
    }
    resolved: dict[str, dict[str, str]] = {}
    if not unresolved:
        return resolved
    path = Path(cache_dir) / "ohlcv_audit.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return resolved
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if record.get("cache_key") != cache_key:
            continue
        vendor = record.get("vendor")
        batch_id = record.get("batch_id")
        audited_dates = record.get("trading_dates")
        if (
            not isinstance(vendor, str)
            or not vendor
            or not isinstance(batch_id, str)
            or not batch_id
            or not isinstance(audited_dates, list)
        ):
            continue
        for trading_date in unresolved.intersection(
            str(value) for value in audited_dates
        ):
            resolved[trading_date] = {
                "vendor": vendor,
                "batch_id": batch_id,
            }
        unresolved.difference_update(resolved)
        if not unresolved:
            break
    return resolved
