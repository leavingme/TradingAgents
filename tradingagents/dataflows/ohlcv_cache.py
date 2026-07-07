"""
Shared OHLCV disk-cache helpers used by all vendor modules.

Cache layout
------------
    {data_cache_dir}/{safe_symbol}.csv

One file per symbol. Rows are accumulated over time: when a request needs data
not yet in the cache, the vendor fetches from the API, the new rows are merged
(deduplicated by Date, sorted chronologically), and the file is rewritten.
Subsequent calls for the same or overlapping windows skip the network entirely.

Staleness
---------
The cache is considered stale when the latest row is more than MAX_STALE_DAYS
calendar days before the requested end_date.  For historical back-tests the
file is reused indefinitely; for live/recent queries it is refreshed when a
new trading day becomes available.
"""
from __future__ import annotations

import os
import re

import pandas as pd

MAX_STALE_DAYS = 10  # matches stockstats_utils.MAX_OHLCV_STALE_DAYS


def symbol_to_cache_key(symbol: str) -> str:
    """
    Convert a ticker symbol to a clean filesystem-safe cache key.

    Examples
    --------
        NVDA.US  -> NVDA_US
        1810.HK  -> 1810_HK
        GC=F     -> GC_F
        ^GSPC    -> GSPC
        NVDA     -> NVDA
    """
    key = re.sub(r"[^A-Za-z0-9_-]", "_", symbol).strip("_")
    return key or "UNKNOWN"


def cache_filepath(cache_dir: str, cache_key: str) -> str:
    """Return the canonical cache path for a symbol cache key."""
    return os.path.join(cache_dir, f"{cache_key}.csv")


def read_cached_ohlcv(
    cache_dir: str,
    cache_key: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame | None:
    """
    Return a DataFrame of OHLCV rows filtered to [start_date, end_date] if the
    cache file exists and is not stale; otherwise return None (cache miss).

    A 'fresh' cache means the file's latest row is within MAX_STALE_DAYS of
    end_date.  Historical queries (end_date well in the past) are served from
    cache indefinitely.
    """
    path = cache_filepath(cache_dir, cache_key)
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, on_bad_lines="skip", encoding="utf-8")
    except Exception:
        return None
    if df.empty or "Close" not in df.columns or "Date" not in df.columns:
        return None

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)

    req_end = pd.to_datetime(end_date)
    latest = df["Date"].max()

    if (req_end - latest).days > MAX_STALE_DAYS:
        return None  # stale: needs a fresh fetch

    req_start = pd.to_datetime(start_date)
    window = df[(df["Date"] >= req_start) & (df["Date"] <= req_end)].copy()
    return window if not window.empty else None


def merge_and_write_ohlcv(
    cache_dir: str,
    cache_key: str,
    new_df: pd.DataFrame,
) -> None:
    """
    Merge new_df into the cache file (if any), deduplicate by Date, sort
    chronologically, and rewrite.

    new_df must contain at least: Date, Open, High, Low, Close, Volume.
    Extra columns are preserved but not guaranteed to survive deduplication.
    """
    path = cache_filepath(cache_dir, cache_key)
    frames: list[pd.DataFrame] = []

    if os.path.exists(path):
        try:
            existing = pd.read_csv(path, on_bad_lines="skip", encoding="utf-8")
            if not existing.empty and "Close" in existing.columns:
                frames.append(existing)
        except Exception:
            pass

    frames.append(new_df.copy())
    combined = pd.concat(frames, ignore_index=True)
    combined["Date"] = pd.to_datetime(combined["Date"], errors="coerce")
    combined = (
        combined.dropna(subset=["Date"])
        .drop_duplicates(subset=["Date"])
        .sort_values("Date")
        .reset_index(drop=True)
    )
    os.makedirs(cache_dir, exist_ok=True)
    combined.to_csv(path, index=False, encoding="utf-8")
