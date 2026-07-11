import logging
import time
from datetime import datetime, timedelta, timezone

from .alpha_vantage import (
    get_balance_sheet as get_alpha_vantage_balance_sheet,
    get_cashflow as get_alpha_vantage_cashflow,
    get_fundamentals as get_alpha_vantage_fundamentals,
    get_global_news as get_alpha_vantage_global_news,
    get_income_statement as get_alpha_vantage_income_statement,
    get_indicator as get_alpha_vantage_indicator,
    get_insider_transactions as get_alpha_vantage_insider_transactions,
    get_news as get_alpha_vantage_news,
    get_stock as get_alpha_vantage_stock,
)
from .config import get_config
from .data_validation import (
    indicator_requires_close,
    latest_verified_close,
    normalize_indicator_result,
    validate_indicator_result,
    validate_vendor_result,
)
from .errors import (
    NoMarketDataError,
    NoUsableFinancialDataError,
    NoUsableTechnicalIndicatorError,
    VendorError,
    VendorNotConfiguredError,
    VendorRateLimitError,
)
from .financial_validation import (
    NormalizedFinancialData,
    normalize_financial_result,
    render_financial_data,
    validate_financial_result,
    reconcile_financials,
    compute_derived_metrics,
    log_financial_audit,
    extract_metric,
)
import threading
import re

_local_state = threading.local()

from .duckduckgo_search import (
    get_global_news_duckduckgo,
    get_news_duckduckgo,
)
from .fred import get_macro_data as get_fred_macro_data
# Longbridge data vendor plugin: ships on top of v0.3.0 (added 2026-07-04).
# CLI variant is the fallback when MCP bearer is missing/expired.
from .longbridge import (
    get_stock_data as get_longbridge_stock,
    get_indicators as get_longbridge_indicators,
    get_fundamentals as get_longbridge_fundamentals,
    get_balance_sheet as get_longbridge_balance_sheet,
    get_cashflow as get_longbridge_cashflow,
    get_income_statement as get_longbridge_income_statement,
)
try:
    from .longbridge_mcp import (
        get_stock_data as get_longbridge_mcp_stock,
        get_indicators as get_longbridge_mcp_indicators,
        get_fundamentals as get_longbridge_mcp_fundamentals,
        get_balance_sheet as get_longbridge_mcp_balance_sheet,
        get_cashflow as get_longbridge_mcp_cashflow,
        get_income_statement as get_longbridge_mcp_income_statement,
    )
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    _LBMCP_NONE = None
    get_longbridge_mcp_stock = _LBMCP_NONE
    get_longbridge_mcp_indicators = _LBMCP_NONE
    get_longbridge_mcp_fundamentals = _LBMCP_NONE
    get_longbridge_mcp_balance_sheet = _LBMCP_NONE
    get_longbridge_mcp_cashflow = _LBMCP_NONE
    get_longbridge_mcp_income_statement = _LBMCP_NONE
from .polymarket import get_prediction_markets as get_polymarket_prediction_markets
from .westock import (
    get_balance_sheet as get_westock_balance_sheet,
    get_cashflow as get_westock_cashflow,
    get_fundamentals as get_westock_fundamentals,
    get_income_statement as get_westock_income_statement,
    get_insider_transactions as get_westock_insider_transactions,
    get_stock_stats_indicators_window,
    get_westock_data_online,
)
from .westock_news import get_global_news_westock, get_news_westock

logger = logging.getLogger(__name__)

FINANCIAL_METHODS = {
    "get_fundamentals",
    "get_balance_sheet",
    "get_cashflow",
    "get_income_statement",
}

# Tools organized by category
TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": [
            "get_stock_data"
        ]
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": [
            "get_indicators"
        ]
    },
    "fundamental_data": {
        "description": "Company fundamentals",
        "tools": [
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement"
        ]
    },
    "news_data": {
        "description": "News and insider data",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ]
    },
    "macro_data": {
        "description": "Macroeconomic indicators (rates, inflation, labor, growth)",
        "tools": [
            "get_macro_indicators",
        ]
    },
    "prediction_markets": {
        "description": "Market-implied probabilities for forward-looking events",
        "tools": [
            "get_prediction_markets",
        ]
    }
}

VENDOR_LIST = [
    "westock",
    "duckduckgo",
    "fred",
    "polymarket",
    "alpha_vantage",
    "longbridge",
    "longbridge_mcp",
]

# Optional enrichment categories. These add macro/event context to the news
# analyst but are not core to a decision, so a vendor failure here degrades to a
# sentinel instead of aborting the run (a bad LLM-supplied indicator, a missing
# key, or a network blip should not crash an analysis over flavour data). Core
# categories (prices, fundamentals, news) still raise so a broken primary is loud.
OPTIONAL_CATEGORIES = {"macro_data", "prediction_markets"}

# Mapping of methods to their vendor-specific implementations
VENDOR_METHODS = {
    # core_stock_apis
    "get_stock_data": {
        "alpha_vantage": get_alpha_vantage_stock,
        "westock": get_westock_data_online,
        "longbridge": get_longbridge_stock,
        "longbridge_mcp": get_longbridge_mcp_stock,
    },
    # technical_indicators
    "get_indicators": {
        "alpha_vantage": get_alpha_vantage_indicator,
        "westock": get_stock_stats_indicators_window,
        "longbridge": get_longbridge_indicators,
        "longbridge_mcp": get_longbridge_mcp_indicators,
    },
    # fundamental_data
    "get_fundamentals": {
        "alpha_vantage": get_alpha_vantage_fundamentals,
        "westock": get_westock_fundamentals,
        "longbridge": get_longbridge_fundamentals,
        "longbridge_mcp": get_longbridge_mcp_fundamentals,
    },
    "get_balance_sheet": {
        "alpha_vantage": get_alpha_vantage_balance_sheet,
        "westock": get_westock_balance_sheet,
        "longbridge": get_longbridge_balance_sheet,
        "longbridge_mcp": get_longbridge_mcp_balance_sheet,
    },
    "get_cashflow": {
        "alpha_vantage": get_alpha_vantage_cashflow,
        "westock": get_westock_cashflow,
        "longbridge": get_longbridge_cashflow,
        "longbridge_mcp": get_longbridge_mcp_cashflow,
    },
    "get_income_statement": {
        "alpha_vantage": get_alpha_vantage_income_statement,
        "westock": get_westock_income_statement,
        "longbridge": get_longbridge_income_statement,
        "longbridge_mcp": get_longbridge_mcp_income_statement,
    },
    # news_data
    "get_news": {
        "westock": get_news_westock,
        "duckduckgo": get_news_duckduckgo,
        "alpha_vantage": get_alpha_vantage_news,
    },
    "get_global_news": {
        "westock": get_global_news_westock,
        "duckduckgo": get_global_news_duckduckgo,
        "alpha_vantage": get_alpha_vantage_global_news,
    },
    "get_insider_transactions": {
        "alpha_vantage": get_alpha_vantage_insider_transactions,
        "westock": get_westock_insider_transactions,
    },
    # macro_data
    "get_macro_indicators": {
        "fred": get_fred_macro_data,
    },
    # prediction_markets
    "get_prediction_markets": {
        "polymarket": get_polymarket_prediction_markets,
    },
}

def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")

def get_vendor(category: str, method: str = None) -> str:
    """Get the configured vendor for a data category or specific tool method.
    Tool-level configuration takes precedence over category-level.
    """
    config = get_config()

    # Check tool-level configuration first (if method provided)
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # Fall back to category-level configuration
    return config.get("data_vendors", {}).get(category, "default")

def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to appropriate vendor implementation with fallback support."""
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(',')]

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    all_available_vendors = list(VENDOR_METHODS[method].keys())

    explicit = [v for v in primary_vendors if v and v != "default"]
    if explicit:
        vendor_chain = [v for v in explicit if v in VENDOR_METHODS[method]]
        if not vendor_chain:
            raise ValueError(
                f"Configured vendor(s) {explicit} not available for '{method}'. "
                f"Available: {all_available_vendors}."
            )
    else:
        vendor_chain = all_available_vendors

    # --- Financial Reconciliation Interception ---
    if method in FINANCIAL_METHODS:
        if getattr(_local_state, "in_reconciliation", False):
            # Inner call (sub-fetch), bypass reconciliation and cache, return raw NormalizedFinancialData
            last_no_data = None
            first_error = None
            for vendor in vendor_chain:
                vendor_impl = VENDOR_METHODS[method][vendor]
                impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl
                try:
                    result = impl_func(*args, **kwargs)
                    if not isinstance(result, NormalizedFinancialData):
                        result = normalize_financial_result(result, source=vendor)
                    return result
                except (VendorRateLimitError, VendorNotConfiguredError, NoMarketDataError) as e:
                    if first_error is None and isinstance(e, VendorNotConfiguredError):
                        first_error = e
                    if isinstance(e, NoMarketDataError):
                        last_no_data = e
                    continue
                except Exception as e:
                    if first_error is None:
                        first_error = e
                    continue
            if last_no_data is not None:
                raise last_no_data
            if first_error is not None:
                raise first_error
            raise NoUsableFinancialDataError(str(args[0]), method.removeprefix("get_"), "All vendors failed in sub-fetch")

        # Outer call, perform reconciliation and caching
        ticker = args[0]
        freq = args[1] if len(args) > 1 else "quarterly"
        curr_date = args[2] if len(args) > 2 and args[2] else None

        impl_ids = tuple(
            id(VENDOR_METHODS[m][v])
            for m in FINANCIAL_METHODS
            for v in vendor_chain
            if m in VENDOR_METHODS and v in VENDOR_METHODS[m]
        )
        cache_key = (ticker, freq, curr_date, impl_ids)
        if not hasattr(_local_state, "financial_cache"):
            _local_state.financial_cache = {}

        if cache_key in _local_state.financial_cache:
            cached_vendor, cached_data_dict = _local_state.financial_cache[cache_key]
            if method in cached_data_dict:
                return cached_data_dict[method]
            raise NoUsableFinancialDataError(
                ticker,
                method.removeprefix("get_"),
                f"Method {method} not available in reconciled cache for vendor {cached_vendor}"
            )

        _local_state.in_reconciliation = True
        last_no_data = None
        first_error = None
        reconciled = False

        try:
            # Fetch verified close price
            share_price = None
            if curr_date:
                try:
                    import datetime as _dt
                    end = _dt.datetime.strptime(curr_date, "%Y-%m-%d")
                    start = (end - _dt.timedelta(days=30)).strftime("%Y-%m-%d")
                    raw_ohlcv = route_to_vendor("get_stock_data", ticker, start, curr_date)
                    share_price = latest_verified_close(raw_ohlcv, curr_date)
                except Exception as exc:
                    logger.debug("Failed to fetch verified close for financial derived metrics: %s", exc)

            for vendor in vendor_chain:
                started = time.monotonic()
                try:
                    is_data = None
                    bs_data = None
                    cf_data = None
                    fd_data = None

                    # IS
                    if "get_income_statement" in VENDOR_METHODS and vendor in VENDOR_METHODS["get_income_statement"]:
                        try:
                            is_data = VENDOR_METHODS["get_income_statement"][vendor](ticker, freq, curr_date)
                            if not isinstance(is_data, NormalizedFinancialData):
                                is_data = normalize_financial_result(is_data, source=vendor)
                            val = validate_financial_result(is_data, curr_date)
                            if not val.is_valid:
                                log_financial_audit(ticker, vendor, "get_income_statement", "invalid", is_data, val.detail)
                                raise NoUsableFinancialDataError(ticker, "income_statement", val.detail)
                        except Exception as e:
                            if method == "get_income_statement":
                                logger.warning("Vendor %s get_income_statement failed: %s", vendor, e)
                                raise
                            else:
                                is_data = None

                    # BS
                    if "get_balance_sheet" in VENDOR_METHODS and vendor in VENDOR_METHODS["get_balance_sheet"]:
                        try:
                            bs_data = VENDOR_METHODS["get_balance_sheet"][vendor](ticker, freq, curr_date)
                            if not isinstance(bs_data, NormalizedFinancialData):
                                bs_data = normalize_financial_result(bs_data, source=vendor)
                            val = validate_financial_result(bs_data, curr_date)
                            if not val.is_valid:
                                log_financial_audit(ticker, vendor, "get_balance_sheet", "invalid", bs_data, val.detail)
                                raise NoUsableFinancialDataError(ticker, "balance_sheet", val.detail)
                        except Exception as e:
                            if method == "get_balance_sheet":
                                logger.warning("Vendor %s get_balance_sheet failed: %s", vendor, e)
                                raise
                            else:
                                bs_data = None

                    # CF
                    if "get_cashflow" in VENDOR_METHODS and vendor in VENDOR_METHODS["get_cashflow"]:
                        try:
                            cf_data = VENDOR_METHODS["get_cashflow"][vendor](ticker, freq, curr_date)
                            if not isinstance(cf_data, NormalizedFinancialData):
                                cf_data = normalize_financial_result(cf_data, source=vendor)
                            val = validate_financial_result(cf_data, curr_date)
                            if not val.is_valid:
                                log_financial_audit(ticker, vendor, "get_cashflow", "invalid", cf_data, val.detail)
                                raise NoUsableFinancialDataError(ticker, "cashflow", val.detail)
                        except Exception as e:
                            if method == "get_cashflow":
                                logger.warning("Vendor %s get_cashflow failed: %s", vendor, e)
                                raise
                            else:
                                cf_data = None

                    # Fundamentals
                    if "get_fundamentals" in VENDOR_METHODS and vendor in VENDOR_METHODS["get_fundamentals"]:
                        try:
                            fd_data = VENDOR_METHODS["get_fundamentals"][vendor](ticker, curr_date)
                            if not isinstance(fd_data, NormalizedFinancialData):
                                fd_data = normalize_financial_result(fd_data, source=vendor)
                            val = validate_financial_result(fd_data, curr_date)
                            if not val.is_valid:
                                log_financial_audit(ticker, vendor, "get_fundamentals", "invalid", fd_data, val.detail)
                                raise NoUsableFinancialDataError(ticker, "fundamentals", val.detail)
                        except Exception as e:
                            if method == "get_fundamentals":
                                logger.warning("Vendor %s get_fundamentals failed: %s", vendor, e)
                                raise
                            else:
                                fd_data = None

                    # Determine period and reconcile
                    is_periods = {m.period for m in is_data.metrics} if is_data else set()
                    bs_periods = {m.period for m in bs_data.metrics} if bs_data else set()
                    cf_periods = {m.period for m in cf_data.metrics} if cf_data else set()

                    present_periods = [p for p in (is_periods, bs_periods, cf_periods) if p]
                    common_periods = set()
                    if len(present_periods) >= 2:
                        common_periods = present_periods[0]
                        for p in present_periods[1:]:
                            common_periods = common_periods & p
                    elif len(present_periods) == 1:
                        common_periods = present_periods[0]

                    active_statements_count = sum(1 for d in (is_data, bs_data, cf_data) if d)
                    if active_statements_count >= 2 and not common_periods:
                        p_detail = f"Period inconsistency: IS periods={is_periods}, BS periods={bs_periods}, CF periods={cf_periods}"
                        for name, d in [("IS", is_data), ("BS", bs_data), ("CF", cf_data)]:
                            if d: log_financial_audit(ticker, vendor, f"get_{name.lower()}", "invalid", d, p_detail)
                        raise NoUsableFinancialDataError(ticker, "financial_reconciliation", p_detail)

                    latest_period = None
                    latest_period_type = "quarterly"
                    if common_periods:
                        def parse_period_key(p_str):
                            m = re.search(r"Q([1-4])\s+(\d{4})", p_str, re.IGNORECASE)
                            if m:
                                return int(m.group(2)), int(m.group(1))
                            m = re.search(r"(?:FY|ANNUAL)\s+(\d{4})", p_str, re.IGNORECASE)
                            if m:
                                return int(m.group(1)), 12
                            m = re.match(r"^\d{4}$", p_str)
                            if m:
                                return int(p_str), 12
                            return 0, 0
                        latest_period = max(common_periods, key=parse_period_key)
                        latest_period_type = "quarterly" if "Q" in latest_period.upper() else "annual"

                        # Reconcile financials only if at least two statements are present
                        if active_statements_count >= 2:
                            is_reconciled, recon_error = reconcile_financials(ticker, latest_period, is_data, bs_data, cf_data)
                            if not is_reconciled:
                                for name, d in [("IS", is_data), ("BS", bs_data), ("CF", cf_data)]:
                                    if d: log_financial_audit(ticker, vendor, f"get_{name.lower()}", "invalid", d, recon_error)
                                raise NoUsableFinancialDataError(ticker, "financial_reconciliation", recon_error)

                    # Compute derived metrics
                    derived = []
                    if latest_period:
                        derived = compute_derived_metrics(
                            latest_period,
                            latest_period_type,
                            is_data,
                            bs_data,
                            cf_data,
                            fd_data,
                            share_price
                        )

                    # Store results in cache
                    data_dict = {}
                    if is_data:
                        data_dict["get_income_statement"] = render_financial_data(is_data, derived)
                        log_financial_audit(ticker, vendor, "get_income_statement", "verified", is_data)
                    if bs_data:
                        data_dict["get_balance_sheet"] = render_financial_data(bs_data, derived)
                        log_financial_audit(ticker, vendor, "get_balance_sheet", "verified", bs_data)
                    if cf_data:
                        data_dict["get_cashflow"] = render_financial_data(cf_data, derived)
                        log_financial_audit(ticker, vendor, "get_cashflow", "verified", cf_data)
                    if fd_data:
                        data_dict["get_fundamentals"] = render_financial_data(fd_data, [])
                        log_financial_audit(ticker, vendor, "get_fundamentals", "verified", fd_data)

                    _local_state.financial_cache[cache_key] = (vendor, data_dict)
                    _record_vendor_verification(vendor, category, method, "available", "analysis", started)
                    reconciled = True
                    break

                except VendorRateLimitError as e:
                    _record_vendor_verification(vendor, category, method, "rate_limited", "analysis", started, e)
                    continue
                except VendorNotConfiguredError as e:
                    _record_vendor_verification(vendor, category, method, "not_configured", "analysis", started, e)
                    if first_error is None:
                        first_error = e
                    continue
                except (NoMarketDataError, NoUsableFinancialDataError) as e:
                    _record_vendor_verification(vendor, category, method, "no_data", "analysis", started, e)
                    last_no_data = e
                    continue
                except Exception as e:
                    _record_vendor_verification(vendor, category, method, "unavailable", "analysis", started, e)
                    if first_error is None:
                        first_error = e
                    continue

            if not reconciled:
                if last_no_data is not None:
                    raise last_no_data
                if first_error is not None:
                    raise first_error
                raise RuntimeError(f"No available vendor for '{method}'")

        finally:
            _local_state.in_reconciliation = False

        cached_vendor, cached_data_dict = _local_state.financial_cache[cache_key]
        if method in cached_data_dict:
            return cached_data_dict[method]
        raise NoUsableFinancialDataError(
            ticker,
            method.removeprefix("get_"),
            f"Method {method} not available in reconciled cache for vendor {cached_vendor}"
        )

    # --- Non-Financial Methods Routing (OHLCV, Indicators, News, etc.) ---
    last_no_data: VendorError | None = None
    first_error: Exception | None = None
    for vendor in vendor_chain:
        vendor_impl = VENDOR_METHODS[method][vendor]
        impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl

        started = time.monotonic()
        try:
            result = impl_func(*args, **kwargs)
            normalized_result = result
            if method == "get_indicators":
                indicator = str(args[1])
                reference_close = None
                if indicator_requires_close(indicator):
                    symbol, curr_date = str(args[0]), str(args[2])
                    end = datetime.strptime(curr_date, "%Y-%m-%d")
                    lookback = max(int(args[3]), 30)
                    start = (end - timedelta(days=lookback)).strftime("%Y-%m-%d")
                    raw_ohlcv = route_to_vendor("get_stock_data", symbol, start, curr_date)
                    reference_close = latest_verified_close(raw_ohlcv, curr_date)
                normalized = normalize_indicator_result(result, indicator, str(args[2]))
                validation = validate_indicator_result(normalized, reference_close=reference_close)
            else:
                validation = validate_vendor_result(method, result)
            if not validation.is_valid:
                if method == "get_indicators":
                    error = NoUsableTechnicalIndicatorError(
                        str(args[0]),
                        str(args[1]),
                        validation.detail or "vendor data failed validation",
                    )
                else:
                    error = NoMarketDataError(
                        str(args[0]) if args else method,
                        detail=validation.detail or "vendor data failed validation",
                    )
                _record_vendor_verification(
                    vendor, category, method, "invalid", "analysis", started, error
                )
                last_no_data = error
                logger.warning(
                    "Vendor %r returned invalid data for %s (%s); trying next vendor.",
                    vendor, method, validation.detail,
                )
                continue
            _record_vendor_verification(vendor, category, method, "available", "analysis", started)
            return normalized_result
        except VendorRateLimitError as e:
            _record_vendor_verification(vendor, category, method, "rate_limited", "analysis", started, e)
            logger.warning("Vendor %r rate-limited for %s; trying next vendor.", vendor, method)
            continue
        except VendorNotConfiguredError as e:
            _record_vendor_verification(vendor, category, method, "not_configured", "analysis", started, e)
            logger.warning("Vendor %r not configured for %s; trying next vendor.", vendor, method)
            if first_error is None:
                first_error = e
            continue
        except NoMarketDataError as e:
            _record_vendor_verification(vendor, category, method, "no_data", "analysis", started, e)
            last_no_data = e
            continue
        except Exception as e:
            _record_vendor_verification(vendor, category, method, "unavailable", "analysis", started, e)
            logger.warning("Vendor %r failed for %s: %s", vendor, method, e)
            if first_error is None:
                first_error = e
            continue
    # Return one explicit, instructive sentinel rather than a vendor-specific
    # empty string, so the agent reports "unavailable" instead of inventing a
    # value. This takes precedence over incidental fallback errors.
    if last_no_data is not None:
        if first_error is not None:
            # A vendor also hit a real error; surface it in logs so the no-data
            # verdict can't hide a broken primary (network/auth/etc.).
            logger.warning(
                "Returning NO_DATA for %s, but a vendor errored earlier: %s",
                method, first_error,
            )
        if method in {"get_stock_data", "get_indicators"} | FINANCIAL_METHODS:
            raise last_no_data
        sym = last_no_data.symbol
        canonical = last_no_data.canonical
        resolved = "" if canonical == sym else f" (resolved to '{canonical}')"
        # Surface the typed error's detail (e.g. "latest row is 2025-06-11 ...
        # stale") so the agent sees the specific reason — invalid symbol, no
        # coverage, or stale data — not just a generic "unavailable".
        reason = f" ({last_no_data.detail})" if last_no_data.detail else ""
        return (
            f"NO_DATA_AVAILABLE: No usable market data for '{sym}'{resolved} from "
            f"any configured vendor{reason}. The symbol may be invalid, delisted, "
            f"not covered, or the vendor returned stale data. Do not estimate or "
            f"fabricate values — report that data is unavailable for this symbol."
        )

    # No vendor returned data and none reported clean "no data" — surface the
    # first real error (e.g. the primary vendor's network failure). Optional
    # enrichment categories degrade to a sentinel instead, so flavour data can't
    # abort the run.
    if first_error is not None:
        if category in OPTIONAL_CATEGORIES:
            logger.warning("Optional %s unavailable for %s: %s", category, method, first_error)
            return (
                f"DATA_UNAVAILABLE: optional {category} could not be retrieved "
                f"({first_error}). Proceed without it; do not fabricate values."
            )
        raise first_error

    raise RuntimeError(f"No available vendor for '{method}'")


def _record_vendor_verification(vendor, category, method, status, source, started, error=None):
    """Best-effort telemetry must never alter vendor routing behavior."""
    try:
        from .vendor_verification import vendor_verification_store

        return vendor_verification_store.record(
            vendor=vendor,
            category=category,
            method=method,
            status=status,
            source=source,
            detail=str(error) if error else None,
            latency_ms=round((time.monotonic() - started) * 1000),
        )
    except Exception as exc:
        logger.debug("Could not persist vendor verification: %s", exc)
        return None


def verify_vendor(vendor: str, category: str):
    """Run one direct, lightweight capability request without fallback."""
    now = datetime.now(timezone.utc).date()
    probes = {
        "core_stock_apis": ("get_stock_data", ("AAPL", str(now - timedelta(days=10)), str(now))),
        "technical_indicators": ("get_indicators", ("AAPL", "rsi", str(now), 30)),
        "fundamental_data": ("get_fundamentals", ("AAPL",)),
        "news_data": ("get_news", ("AAPL", str(now - timedelta(days=7)), str(now))),
        "macro_data": ("get_macro_indicators", ("cpi", str(now), 365)),
        "prediction_markets": ("get_prediction_markets", ("Federal Reserve interest rates", 3)),
    }
    if category not in probes:
        raise ValueError(f"Unknown vendor category: {category}")
    method, args = probes[category]
    vendor_impl = VENDOR_METHODS.get(method, {}).get(vendor)
    if vendor_impl is None:
        raise ValueError(f"Vendor '{vendor}' does not support '{category}'")
    impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl
    started = time.monotonic()
    try:
        result = impl_func(*args)
        if result is None or (isinstance(result, str) and not result.strip()):
            raise NoMarketDataError("verification probe", detail="vendor returned an empty result")
    except VendorRateLimitError as exc:
        record = _record_vendor_verification(vendor, category, method, "rate_limited", "manual", started, exc)
    except VendorNotConfiguredError as exc:
        record = _record_vendor_verification(vendor, category, method, "not_configured", "manual", started, exc)
    except NoMarketDataError as exc:
        record = _record_vendor_verification(vendor, category, method, "no_data", "manual", started, exc)
    except Exception as exc:
        record = _record_vendor_verification(vendor, category, method, "unavailable", "manual", started, exc)
    else:
        record = _record_vendor_verification(vendor, category, method, "available", "manual", started)
    return record
