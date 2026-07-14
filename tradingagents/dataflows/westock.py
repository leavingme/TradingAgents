"""Westock dataflow implementation.

This module exposes first-class Westock vendor functions. Cross-vendor fallback
is exclusively controlled by ``dataflows.interface.route_to_vendor``.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

import pandas as pd
from dateutil.relativedelta import relativedelta

from .config import get_config
from .data_validation import (
    IndicatorBatch,
    IndicatorObservation,
    NormalizedIndicatorData,
)
from .indicator_requirements import (
    effective_indicator_lookback_days,
    indicator_calculation_lookback_days,
)
from .stockstats_utils import (
    _assert_ohlcv_not_stale,
    filter_financials_by_date,
    load_ohlcv,
)
from .symbol_utils import NoMarketDataError, normalize_symbol

logger = logging.getLogger(__name__)

SUPPORTED_STOCKSTATS_INDICATORS = {
    "close_50_sma", "close_200_sma", "close_10_ema",
    "macd", "macds", "macdh", "rsi", "boll", "boll_ub", "boll_lb",
    "atr", "vwma", "mfi",
}


def get_westock_data_online(
    symbol: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Retrieve OHLCV stock price data from Westock only."""
    from .symbol_utils import is_westock_available, run_westock, to_westock_code

    canonical = normalize_symbol(symbol)
    resolved = "" if canonical == symbol else f" (resolved to {canonical})"

    # 1. Try westock-data
    if is_westock_available():
        w_code = to_westock_code(symbol)
        logger.info("westock-data available; fetching OHLCV for %s (mapped to %s)", symbol, w_code)
        try:
            # We want to pull ~365 observations
            raw = run_westock(["kline", w_code, "--period", "day", "--limit", "365"], raw=True)
            import json
            klines = json.loads(raw)
            if klines and isinstance(klines, list):
                df = pd.DataFrame(klines)
                df = df.rename(columns={
                    "last": "Close",
                    "open": "Open",
                    "high": "High",
                    "low": "Low",
                    "volume": "Volume"
                })
                if "date" in df.columns:
                    df = df.rename(columns={"date": "Date"})
                df["RawTimestamp"] = df["Date"].astype(str)
                df["Date"] = pd.to_datetime(df["Date"])
                for col in ["Open", "High", "Low", "Close"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                if "Volume" in df.columns:
                    df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce")
                
                df = df.sort_values("Date").reset_index(drop=True)
                df = df[(df["Date"] >= start_date) & (df["Date"] <= end_date)]
                from .ohlcv_cache import (
                    filter_completed_daily_bars,
                    merge_and_write_ohlcv,
                    symbol_to_cache_key,
                )
                from .ohlcv_model import batch_from_frame
                cache_key = symbol_to_cache_key(canonical)
                df = filter_completed_daily_bars(df, cache_key)
                
                if not df.empty:
                    batch = batch_from_frame(
                        df,
                        symbol=canonical,
                        vendor="westock",
                        adapter_version="westock_ohlcv_v1",
                        timezone_semantics="exchange_local_trading_date",
                        raw_timestamps=df["RawTimestamp"].astype(str).tolist(),
                    )
                    merge_and_write_ohlcv(
                        get_config()["data_cache_dir"], cache_key, batch
                    )
                    df = df.drop(columns=["RawTimestamp"])
                    df = df.set_index("Date")
                    csv_string = df.to_csv()
                    header = f"# Stock data for {symbol}{resolved} (via westock-data) from {start_date} to {end_date}\n"
                    header += f"# Total records: {len(df)}\n"
                    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    return header + csv_string
        except Exception as exc:
            raise NoMarketDataError(
                symbol,
                canonical,
                f"Westock kline request failed: {exc}",
            ) from exc

    raise NoMarketDataError(symbol, canonical, "Westock is not available")


def get_stock_stats_indicators_window(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator to get the analysis and report of"],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"],
) -> str:
    best_ind_params = {
        # Moving Averages
        "close_50_sma": (
            "50 SMA: A medium-term trend indicator. "
            "Usage: Identify trend direction and serve as dynamic support/resistance. "
            "Tips: It lags price; combine with faster indicators for timely signals."
        ),
        "close_200_sma": (
            "200 SMA: A long-term trend benchmark. "
            "Usage: Confirm overall market trend and identify golden/death cross setups. "
            "Tips: It reacts slowly; best for strategic trend confirmation rather than frequent trading entries."
        ),
        "close_10_ema": (
            "10 EMA: A responsive short-term average. "
            "Usage: Capture quick shifts in momentum and potential entry points. "
            "Tips: Prone to noise in choppy markets; use alongside longer averages for filtering false signals."
        ),
        # MACD Related
        "macd": (
            "MACD: Computes momentum via differences of EMAs. "
            "Usage: Look for crossovers and divergence as signals of trend changes. "
            "Tips: Confirm with other indicators in low-volatility or sideways markets."
        ),
        "macds": (
            "MACD Signal: An EMA smoothing of the MACD line. "
            "Usage: Use crossovers with the MACD line to trigger trades. "
            "Tips: Should be part of a broader strategy to avoid false positives."
        ),
        "macdh": (
            "MACD Histogram: Shows the gap between the MACD line and its signal. "
            "Usage: Visualize momentum strength and spot divergence early. "
            "Tips: Can be volatile; complement with additional filters in fast-moving markets."
        ),
        # Momentum Indicators
        "rsi": (
            "RSI: Measures momentum to flag overbought/oversold conditions. "
            "Usage: Apply 70/30 thresholds and watch for divergence to signal reversals. "
            "Tips: In strong trends, RSI may remain extreme; always cross-check with trend analysis."
        ),
        # Volatility Indicators
        "boll": (
            "Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands. "
            "Usage: Acts as a dynamic benchmark for price movement. "
            "Tips: Combine with the upper and lower bands to effectively spot breakouts or reversals."
        ),
        "boll_ub": (
            "Bollinger Upper Band: Typically 2 standard deviations above the middle line. "
            "Usage: Signals potential overbought conditions and breakout zones. "
            "Tips: Confirm signals with other tools; prices may ride the band in strong trends."
        ),
        "boll_lb": (
            "Bollinger Lower Band: Typically 2 standard deviations below the middle line. "
            "Usage: Indicates potential oversold conditions. "
            "Tips: Use additional analysis to avoid false reversal signals."
        ),
        "atr": (
            "ATR: Averages true range to measure volatility. "
            "Usage: Set stop-loss levels and adjust position sizes based on current market volatility. "
            "Tips: It's a reactive measure, so use it as part of a broader risk management strategy."
        ),
        # Volume-Based Indicators
        "vwma": (
            "VWMA: A moving average weighted by volume. "
            "Usage: Confirm trends by integrating price action with volume data. "
            "Tips: Watch for skewed results from volume spikes; use in combination with other volume analyses."
        ),
        "mfi": (
            "MFI: The Money Flow Index is a momentum indicator that uses both price and volume to measure buying and selling pressure. "
            "Usage: Identify overbought (>80) or oversold (<20) conditions and confirm the strength of trends or reversals. "
            "Tips: Use alongside RSI or MACD to confirm signals; divergence between price and MFI can indicate potential reversals."
        ),
    }

    if indicator not in best_ind_params:
        raise ValueError(
            f"Indicator {indicator} is not supported. Please choose from: {list(best_ind_params.keys())}"
        )

    end_date = curr_date
    curr_date_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    before = curr_date_dt - relativedelta(days=look_back_days)
    from .indicator_requirements import indicator_calculation_lookback_days

    calculation_days = indicator_calculation_lookback_days(
        indicator, look_back_days
    )
    calculation_start = (
        curr_date_dt - relativedelta(days=calculation_days)
    ).strftime("%Y-%m-%d")

    try:
        indicator_data = _get_stock_stats_bulk(
            symbol,
            indicator,
            curr_date,
            calculation_start=calculation_start,
        )

        current_dt = curr_date_dt
        date_values = []

        while current_dt >= before:
            date_str = current_dt.strftime('%Y-%m-%d')

            if date_str in indicator_data:
                indicator_value = indicator_data[date_str]
            else:
                indicator_value = "N/A: Not a trading day (weekend or holiday)"

            date_values.append((date_str, indicator_value))
            current_dt = current_dt - relativedelta(days=1)

        ind_string = ""
        for date_str, value in date_values:
            ind_string += f"{date_str}: {value}\n"

    except NoMarketDataError:
        raise
    except Exception as e:
        logger.error("Error getting bulk stockstats data: %s", e)
        ind_string = ""
        curr_date_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        while curr_date_dt >= before:
            indicator_value = get_stockstats_indicator(
                symbol,
                indicator,
                curr_date_dt.strftime("%Y-%m-%d"),
                calculation_start=calculation_start,
            )
            ind_string += f"{curr_date_dt.strftime('%Y-%m-%d')}: {indicator_value}\n"
            curr_date_dt = curr_date_dt - relativedelta(days=1)

    result_str = (
        f"## {indicator} values from {before.strftime('%Y-%m-%d')} to {end_date}:\n\n"
        + ind_string
        + "\n\n"
        + best_ind_params.get(indicator, "No description available.")
    )

    return result_str


def get_stock_stats_indicators_batch(
    symbol: str,
    indicators: list[str] | tuple[str, ...],
    curr_date: str,
    look_back_days: int,
) -> IndicatorBatch:
    """Calculate several indicators from one canonical OHLCV load and frame."""
    requested = tuple(
        dict.fromkeys(
            str(item).lower().strip() for item in indicators if str(item).strip()
        )
    )
    if not requested:
        raise ValueError("At least one indicator is required")
    if len(requested) > 8:
        raise ValueError("At most 8 indicators may be requested in one batch")

    unsupported = [
        item for item in requested if item not in SUPPORTED_STOCKSTATS_INDICATORS
    ]
    if unsupported:
        raise ValueError(f"Unsupported indicators: {', '.join(unsupported)}")

    end = pd.Timestamp(curr_date)
    output_days = {
        item: effective_indicator_lookback_days(item, int(look_back_days))
        for item in requested
    }
    calculation_days = max(
        indicator_calculation_lookback_days(item, output_days[item])
        for item in requested
    )
    calculation_start = (end - pd.Timedelta(days=calculation_days)).strftime("%Y-%m-%d")
    data = load_ohlcv(symbol, curr_date)
    data = data[
        (data["Date"] >= pd.Timestamp(calculation_start)) & (data["Date"] <= end)
    ].copy()
    if data.empty:
        raise NoMarketDataError(
            symbol, detail=f"No OHLCV rows on or after calculation start {calculation_start}"
        )

    from stockstats import wrap

    stock_frame = wrap(data)
    failures: list[tuple[str, str]] = []
    series: list[NormalizedIndicatorData] = []
    for indicator in requested:
        try:
            stock_frame[indicator]
            display_start = end - pd.Timedelta(days=output_days[indicator])
            values = pd.DataFrame({
                "Date": pd.to_datetime(stock_frame["Date"], errors="coerce"),
                "Value": pd.to_numeric(stock_frame[indicator], errors="coerce"),
            })
            values = values[
                (values["Date"] >= display_start)
                & (values["Date"] <= end)
                & values["Value"].notna()
            ]
            observations = tuple(
                IndicatorObservation(pd.Timestamp(row.Date), float(row.Value))
                for row in values.itertuples(index=False)
            )
            source_text = "\n".join([
                f"## {indicator} values from {display_start.strftime('%Y-%m-%d')} to {curr_date}:",
                "",
                *(f"{item.date.strftime('%Y-%m-%d')}: {item.value}" for item in observations),
                "",
                "Data Source: westock local stockstats over canonical OHLCV",
            ])
            series.append(NormalizedIndicatorData(
                indicator=indicator,
                analysis_date=end,
                observations=observations,
                bars=len(observations),
                source_text=source_text,
            ))
        except Exception as exc:
            failures.append((indicator, f"{type(exc).__name__}: {exc}"))

    latest_row = data.sort_values("Date").iloc[-1]
    return IndicatorBatch(
        symbol=normalize_symbol(symbol),
        analysis_date=curr_date,
        vendor="westock",
        requested_indicators=requested,
        series=tuple(series),
        latest_ohlcv_date=pd.Timestamp(latest_row["Date"]).strftime("%Y-%m-%d"),
        reference_close=float(latest_row["Close"]),
        calculation_start=calculation_start,
        failures=tuple(failures),
    )


def _get_stock_stats_bulk(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator to calculate"],
    curr_date: Annotated[str, "current date for reference"],
    calculation_start: str | None = None,
) -> dict:
    from stockstats import wrap

    data = load_ohlcv(symbol, curr_date)
    if calculation_start:
        data = data[data["Date"] >= pd.Timestamp(calculation_start)].copy()
        if data.empty:
            raise NoMarketDataError(
                symbol,
                detail=f"No OHLCV rows on or after calculation start {calculation_start}",
            )
    df = wrap(data)
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")

    df[indicator]

    result_dict = {}
    for _, row in df.iterrows():
        date_str = row["Date"]
        indicator_value = row[indicator]

        if pd.isna(indicator_value):
            result_dict[date_str] = "N/A"
        else:
            result_dict[date_str] = str(indicator_value)

    return result_dict


def get_stockstats_indicator(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator to get the analysis and report of"],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
    calculation_start: str | None = None,
) -> str:
    curr_date_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    curr_date = curr_date_dt.strftime("%Y-%m-%d")

    try:
        indicator_value = StockstatsUtils.get_stock_stats(
            symbol,
            indicator,
            curr_date,
            calculation_start=calculation_start,
        )
    except NoMarketDataError:
        raise
    except Exception as e:
        raise NoMarketDataError(
            symbol,
            detail=f"Westock could not calculate {indicator}: {e}",
        ) from e

    return str(indicator_value)


def get_fundamentals(
    ticker: Annotated[str, "ticker symbol of the company"],
    curr_date: Annotated[str, "current date"] = None,
) -> str:
    """Get company fundamentals overview."""
    from .symbol_utils import is_westock_available, to_westock_code, run_westock

    canonical = normalize_symbol(ticker)
    
    # 1. Try westock-data profile
    if is_westock_available():
        w_code = to_westock_code(ticker)
        logger.info("westock-data available; fetching fundamentals for %s (mapped to %s)", ticker, w_code)
        try:
            raw = run_westock(["profile", w_code], raw=True)
            import json
            res = json.loads(raw)
            if res and res.get("success") and isinstance(res.get("data"), dict):
                data = res["data"]
                from .financial_validation import NormalizedFinancialData
                return NormalizedFinancialData(
                    metrics=(),
                    source_text="",
                    raw_payload=res,
                    entity_metadata={
                        "symbol": canonical,
                        "name": data.get("name"),
                        "industry": data.get("industry"),
                        "website": data.get("website"),
                        "vendor": "westock",
                    },
                )
        except Exception as exc:
            raise NoMarketDataError(
                ticker, canonical, f"Westock fundamentals request failed: {exc}"
            ) from exc

    raise NoMarketDataError(ticker, canonical, "Westock fundamentals are not available")


def get_balance_sheet(
    ticker: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency of data: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Westock does not currently expose balance-sheet data directly."""
    raise NoMarketDataError(ticker, detail="Westock balance-sheet data are not available")


def get_cashflow(
    ticker: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency of data: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Westock does not currently expose cash-flow data directly."""
    raise NoMarketDataError(ticker, detail="Westock cash-flow data are not available")


def get_income_statement(
    ticker: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency of data: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Westock does not currently expose income-statement data directly."""
    raise NoMarketDataError(ticker, detail="Westock income-statement data are not available")


def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol of the company"],
) -> str:
    """Get insider transactions data."""
    return f"No insider transactions reported for symbol '{ticker}'"
