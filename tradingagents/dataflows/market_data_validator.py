"""Deterministic market-data verification snapshot.

The market analyst is an LLM that can confabulate exact numbers — citing a
Bollinger band or a "historically validated bounce" that the underlying data
doesn't support (#830). This module computes a ground-truth snapshot (latest
OHLCV row on or before the analysis date, common indicators, recent closes)
the analyst is told to treat as the source of truth for any exact numeric
claim. Deterministic, no LLM involved.

Data source: routes through ``data_vendors.core_stock_apis`` (default
``longbridge_mcp, longbridge, westock``). Validation and fallback are owned by
the shared vendor router.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from io import StringIO
import pandas as pd
from stockstats import wrap

from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.dataflows.indicator_requirements import INDICATOR_CALCULATION_HISTORY_DAYS


@dataclass(frozen=True)
class VerifiedMarketSnapshot:
    symbol: str
    market_date: str
    close: float
    atr: float
    vendor_call_id: str
    calculation_start: str
    row_count: int

# A fixed, common indicator set so the snapshot is the same shape every run.
DEFAULT_SNAPSHOT_INDICATORS: tuple[str, ...] = (
    "close_10_ema", "close_50_sma", "close_200_sma",
    "rsi", "boll", "boll_ub", "boll_lb",
    "macd", "macds", "macdh", "atr",
)


def _parse_vendor_csv(raw: object) -> pd.DataFrame:
    """Coerce a vendor's OHLCV payload into a DataFrame.

    Longbridge MCP returns a piped, box-drawn ASCII table (whitespace-separated,
    decorated headers — `Date                  Open ...`) with a leading comment
    block; Longbridge CLI returns a more conventional CSV after a comment header;
    Westock already returns a DataFrame.
    """
    if isinstance(raw, pd.DataFrame):
        return raw
    if not raw:
        return pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    text = str(raw).strip()

    # Drop the leading "# ..." comment lines, but keep the actual table.
    lines = []
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        # Box-drawing separator lines (Longbridge MCP uses '─' characters).
        if line and all(ch in "─-= \t" for ch in line):
            continue
        lines.append(line)
    cleaned = "\n".join(lines)

    # If the table header contains 'Date' (any case), use whitespace separation;
    # else fall through to comma (CSV) parsing. Both shapes appear in the wild.
    header_line = next(
        (ln for ln in cleaned.splitlines()
         if ln.lstrip().lower().startswith("date")),
        None,
    )
    if header_line and "," not in header_line:
        try:
            return pd.read_csv(
                StringIO(cleaned),
                sep=r"\s+",
                engine="python",
            )
        except Exception:
            pass  # fall through to CSV path

    return pd.read_csv(StringIO(cleaned))


def _load_ohlcv(symbol: str, curr_date: str) -> pd.DataFrame:
    """OHLCV via the configured ``core_stock_apis`` vendor chain.

    Honours the user's ``data_vendors.core_stock_apis`` setting (typically
    ``longbridge_mcp, longbridge, westock``). The shared router validates each
    result and controls all fallback behavior.
    """
    # Use the same deterministic calculation horizon as routed indicators so
    # trusted ATR/EMA values cannot silently use a different seed window.
    import datetime as _dt
    end = _dt.datetime.strptime(curr_date, "%Y-%m-%d")
    start = (end - _dt.timedelta(days=INDICATOR_CALCULATION_HISTORY_DAYS)).strftime("%Y-%m-%d")
    raw = route_to_vendor("get_stock_data", symbol, start, curr_date)
    return _parse_vendor_csv(raw)


def _verified_rows(symbol: str, curr_date: str) -> pd.DataFrame:
    """OHLCV on or before curr_date, date-sorted. Raises if nothing usable.

    ``_load_ohlcv`` already normalizes the Date column and filters out
    look-ahead rows, but we re-apply the cutoff defensively — this is a
    verification path, so it must not trust its input to be pre-filtered.
    """
    data = _load_ohlcv(symbol, curr_date)
    if data is None or data.empty:
        raise ValueError(f"No OHLCV data available for {symbol}.")

    df = data.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce", utc=True)
    df = df.dropna(subset=["Date"])
    # Longbridge MCP returns timezone-aware timestamps ("2026-07-02T04:00:00Z");
    # strip the tz for comparison against the naïve analysis date. TradingAgents
    # only models calendar dates, never sub-day precision at the snapshot layer.
    cutoff = pd.to_datetime(curr_date)
    if df["Date"].dt.tz is not None:
        df["Date"] = df["Date"].dt.tz_convert("UTC").dt.tz_localize(None)
    df = df[df["Date"] <= cutoff].sort_values("Date")
    if df.empty:
        raise ValueError(f"No OHLCV rows on or before {curr_date} for {symbol}.")
    return df


def _fmt(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def build_verified_market_snapshot(
    symbol: str,
    curr_date: str,
    look_back_days: int = 30,
    indicators: Iterable[str] | None = None,
) -> str:
    """Render a ground-truth snapshot: latest OHLCV row, indicators, recent closes."""
    # `df` keeps the original capitalized OHLCV columns (Open/High/Low/Close/
    # Volume); stockstats `wrap()` lowercases columns and adds indicator
    # columns, so read raw prices from `df` and indicators from `stock_df`.
    _, df, stock_df = build_verified_market_snapshot_data(
        symbol, curr_date, require_audit=False
    )

    selected = tuple(indicators or DEFAULT_SNAPSHOT_INDICATORS)
    indicator_values: dict[str, str] = {}
    for name in selected:
        try:
            stock_df[name]  # triggers stockstats calculation
            indicator_values[name] = _fmt(stock_df.iloc[-1][name])
        except Exception as exc:  # noqa: BLE001 — one bad indicator shouldn't sink the snapshot
            indicator_values[name] = f"N/A ({type(exc).__name__})"

    latest = df.iloc[-1]
    latest_date = _fmt(latest["Date"])
    window = max(1, min(int(look_back_days), 30))
    recent = df.tail(window)

    lines = [
        f"## Verified market data snapshot for {symbol.upper()}",
        "",
        f"- Requested analysis date: {curr_date}",
        f"- Latest trading row used: {latest_date}",
        "- Rows after the requested analysis date are excluded before verification.",
        "",
        "### Latest verified OHLCV row",
        "",
        "| Field | Value |",
        "|---|---:|",
    ]
    for field in ("Open", "High", "Low", "Close", "Volume"):
        lines.append(f"| {field} | {_fmt(latest.get(field))} |")

    lines += ["", "### Verified technical indicators (latest row)", "",
              "| Indicator | Value |", "|---|---:|"]
    for name, value in indicator_values.items():
        lines.append(f"| {name} | {value} |")

    lines += ["", f"### Recent verified closes (last {len(recent)} rows)", "",
              "| Date | Close |", "|---|---:|"]
    for _, row in recent.iterrows():
        lines.append(f"| {_fmt(row['Date'])} | {_fmt(row.get('Close'))} |")

    lines += [
        "",
        "Use this snapshot as the source of truth for exact OHLCV, price-level, "
        "and indicator-value claims. If another tool output conflicts with it, "
        "flag the discrepancy rather than inventing a reconciled number. Do not "
        "claim historical validation, support/resistance bounces, or exact "
        "percentage moves unless directly supported by tool output with concrete "
        "dates and prices.",
    ]
    return "\n".join(lines)


def build_verified_market_snapshot_data(
    symbol: str,
    curr_date: str,
    *,
    require_audit: bool = True,
) -> tuple[VerifiedMarketSnapshot, pd.DataFrame, pd.DataFrame]:
    """Build the structured trusted snapshot used by trade validation."""
    df = _verified_rows(symbol, curr_date)
    stock_df = wrap(df.copy())
    stock_df["atr"]
    latest = df.iloc[-1]
    atr = float(stock_df.iloc[-1]["atr"])
    close = float(latest["Close"])
    if not pd.notna(atr) or atr <= 0 or close <= 0:
        raise ValueError("Verified snapshot has invalid Close or ATR")

    from tradingagents.runtime.audit_context import current_run_id
    from tradingagents.runtime.history import history_store

    run_id = current_run_id()
    vendor_call_id = ""
    if run_id:
        calls = history_store.get_vendor_calls(run_id)
        selected = [
            call for call in calls
            if call.get("method") == "get_stock_data"
            and call.get("selected")
            and str(call.get("symbol", "")).upper() == symbol.upper()
        ]
        if selected:
            vendor_call_id = str(selected[-1]["call_id"])
    if require_audit and not vendor_call_id:
        raise ValueError("Verified snapshot is not bound to an audited vendor call")

    market_date = pd.Timestamp(latest["Date"]).strftime("%Y-%m-%d")
    calculation_start = (
        pd.Timestamp(curr_date) - pd.Timedelta(days=INDICATOR_CALCULATION_HISTORY_DAYS)
    ).strftime("%Y-%m-%d")
    snapshot = VerifiedMarketSnapshot(
        symbol=symbol.upper(),
        market_date=market_date,
        close=close,
        atr=atr,
        vendor_call_id=vendor_call_id,
        calculation_start=calculation_start,
        row_count=len(df),
    )
    return snapshot, df, stock_df


def verified_snapshot_dict(symbol: str, curr_date: str) -> dict:
    snapshot, _, _ = build_verified_market_snapshot_data(symbol, curr_date)
    return asdict(snapshot)
