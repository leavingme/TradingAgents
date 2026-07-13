import logging
import time
import hashlib
import json
from uuid import uuid4
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
    latest_verified_ohlcv_date,
    normalize_indicator_result,
    validate_indicator_result,
    validate_vendor_result,
)
from .indicator_requirements import effective_indicator_lookback_days
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
from .bird import get_social_posts as get_bird_social_posts
from .social_data import SocialFeed, validate_social_feed
# Longbridge data vendor plugin: ships on top of v0.3.0 (added 2026-07-04).
# CLI variant is the fallback when MCP bearer is missing/expired.
from .longbridge import (
    get_stock_data as get_longbridge_stock,
    get_indicators as get_longbridge_indicators,
    get_fundamentals as get_longbridge_fundamentals,
    get_balance_sheet as get_longbridge_balance_sheet,
    get_cashflow as get_longbridge_cashflow,
    get_income_statement as get_longbridge_income_statement,
    get_news as get_longbridge_news,
    get_global_news as get_longbridge_global_news,
)
try:
    from .longbridge_mcp import (
        get_stock_data as get_longbridge_mcp_stock,
        get_indicators as get_longbridge_mcp_indicators,
        get_fundamentals as get_longbridge_mcp_fundamentals,
        get_balance_sheet as get_longbridge_mcp_balance_sheet,
        get_cashflow as get_longbridge_mcp_cashflow,
        get_income_statement as get_longbridge_mcp_income_statement,
        get_news as get_longbridge_mcp_news,
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
    get_longbridge_mcp_news = _LBMCP_NONE
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
    "social_data": {
        "description": "Ticker-specific social sentiment posts",
        "tools": ["get_social_posts"],
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
    "bird",
]

# Prediction markets remain optional enrichment. Macro observations are
# decision evidence and therefore fail with typed errors instead of a text
# sentinel that could be mistaken for validated data.
OPTIONAL_CATEGORIES = {"prediction_markets"}

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
        "longbridge_mcp": get_longbridge_mcp_news,
        "longbridge": get_longbridge_news,
        "westock": get_news_westock,
        "duckduckgo": get_news_duckduckgo,
        "alpha_vantage": get_alpha_vantage_news,
    },
    "get_global_news": {
        "longbridge": get_longbridge_global_news,
        "westock": get_global_news_westock,
        "duckduckgo": get_global_news_duckduckgo,
        "alpha_vantage": get_alpha_vantage_global_news,
    },
    "get_insider_transactions": {
        "alpha_vantage": get_alpha_vantage_insider_transactions,
        "westock": get_westock_insider_transactions,
    },
    "get_social_posts": {
        "bird": get_bird_social_posts,
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
    if method == "get_indicators" and len(args) >= 4:
        normalized_args = list(args)
        normalized_args[3] = effective_indicator_lookback_days(
            str(normalized_args[1]), int(normalized_args[3])
        )
        args = tuple(normalized_args)

    category = get_category_for_method(method)
    audit_call_id = uuid4().hex
    audit_arguments = _safe_audit_arguments(args, kwargs)
    audit_metadata = _vendor_audit_metadata(method, args, category)

    def record_attempt(
        vendor: str,
        status: str,
        started: float,
        error: Exception | None = None,
        *,
        attempt: int,
        selected: bool = False,
        result: object = None,
    ):
        return _record_vendor_verification(
            vendor, category, method, status, "analysis", started, error,
            call_id=audit_call_id,
            attempt=attempt,
            selected=selected,
            arguments_json=audit_arguments,
            result=result,
            audit_metadata=audit_metadata,
        )
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
            for attempt, vendor in enumerate(vendor_chain, start=1):
                vendor_impl = VENDOR_METHODS[method][vendor]
                impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl
                started = time.monotonic()
                try:
                    result = impl_func(*args, **kwargs)
                    if not isinstance(result, NormalizedFinancialData):
                        result = normalize_financial_result(result, source=vendor)
                    record_attempt(
                        vendor, "available", started, attempt=attempt,
                        selected=True, result=result,
                    )
                    return result
                except (VendorRateLimitError, VendorNotConfiguredError, NoMarketDataError) as e:
                    status = (
                        "rate_limited" if isinstance(e, VendorRateLimitError)
                        else "not_configured" if isinstance(e, VendorNotConfiguredError)
                        else "no_data"
                    )
                    record_attempt(vendor, status, started, e, attempt=attempt)
                    if first_error is None and isinstance(e, VendorNotConfiguredError):
                        first_error = e
                    if isinstance(e, NoMarketDataError):
                        last_no_data = e
                    continue
                except Exception as e:
                    record_attempt(vendor, "unavailable", started, e, attempt=attempt)
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
                started = time.monotonic()
                record_attempt(
                    cached_vendor, "cache_hit", started, attempt=1,
                    selected=True, result=cached_data_dict[method],
                )
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

            for attempt, vendor in enumerate(vendor_chain, start=1):
                started = time.monotonic()
                try:
                    is_data = None
                    bs_data = None
                    cf_data = None
                    fd_data = None

                    def record_financial_subcall(
                        submethod: str,
                        sub_started: float,
                        status: str,
                        *,
                        error: Exception | None = None,
                        result: object = None,
                    ) -> None:
                        _record_vendor_verification(
                            vendor,
                            category,
                            submethod,
                            status,
                            "analysis",
                            sub_started,
                            error,
                            call_id=f"{audit_call_id}:{submethod}:{attempt}",
                            attempt=1,
                            selected=False,
                            arguments_json=audit_arguments,
                            result=result,
                            audit_metadata=audit_metadata,
                        )

                    # IS
                    if "get_income_statement" in VENDOR_METHODS and vendor in VENDOR_METHODS["get_income_statement"]:
                        sub_started = time.monotonic()
                        try:
                            is_data = VENDOR_METHODS["get_income_statement"][vendor](ticker, freq, curr_date)
                            if not isinstance(is_data, NormalizedFinancialData):
                                is_data = normalize_financial_result(is_data, source=vendor)
                            val = validate_financial_result(is_data, curr_date)
                            if not val.is_valid:
                                log_financial_audit(ticker, vendor, "get_income_statement", "invalid", is_data, val.detail)
                                raise NoUsableFinancialDataError(ticker, "income_statement", val.detail)
                            record_financial_subcall(
                                "get_income_statement", sub_started, "available", result=is_data
                            )
                        except Exception as e:
                            record_financial_subcall(
                                "get_income_statement", sub_started, "unavailable", error=e,
                                result=is_data,
                            )
                            if method == "get_income_statement":
                                logger.warning("Vendor %s get_income_statement failed: %s", vendor, e)
                                raise
                            else:
                                is_data = None

                    # BS
                    if "get_balance_sheet" in VENDOR_METHODS and vendor in VENDOR_METHODS["get_balance_sheet"]:
                        sub_started = time.monotonic()
                        try:
                            bs_data = VENDOR_METHODS["get_balance_sheet"][vendor](ticker, freq, curr_date)
                            if not isinstance(bs_data, NormalizedFinancialData):
                                bs_data = normalize_financial_result(bs_data, source=vendor)
                            val = validate_financial_result(bs_data, curr_date)
                            if not val.is_valid:
                                log_financial_audit(ticker, vendor, "get_balance_sheet", "invalid", bs_data, val.detail)
                                raise NoUsableFinancialDataError(ticker, "balance_sheet", val.detail)
                            record_financial_subcall(
                                "get_balance_sheet", sub_started, "available", result=bs_data
                            )
                        except Exception as e:
                            record_financial_subcall(
                                "get_balance_sheet", sub_started, "unavailable", error=e,
                                result=bs_data,
                            )
                            if method == "get_balance_sheet":
                                logger.warning("Vendor %s get_balance_sheet failed: %s", vendor, e)
                                raise
                            else:
                                bs_data = None

                    # CF
                    if "get_cashflow" in VENDOR_METHODS and vendor in VENDOR_METHODS["get_cashflow"]:
                        sub_started = time.monotonic()
                        try:
                            cf_data = VENDOR_METHODS["get_cashflow"][vendor](ticker, freq, curr_date)
                            if not isinstance(cf_data, NormalizedFinancialData):
                                cf_data = normalize_financial_result(cf_data, source=vendor)
                            val = validate_financial_result(cf_data, curr_date)
                            if not val.is_valid:
                                log_financial_audit(ticker, vendor, "get_cashflow", "invalid", cf_data, val.detail)
                                raise NoUsableFinancialDataError(ticker, "cashflow", val.detail)
                            record_financial_subcall(
                                "get_cashflow", sub_started, "available", result=cf_data
                            )
                        except Exception as e:
                            record_financial_subcall(
                                "get_cashflow", sub_started, "unavailable", error=e,
                                result=cf_data,
                            )
                            if method == "get_cashflow":
                                logger.warning("Vendor %s get_cashflow failed: %s", vendor, e)
                                raise
                            else:
                                cf_data = None

                    # Fundamentals
                    if "get_fundamentals" in VENDOR_METHODS and vendor in VENDOR_METHODS["get_fundamentals"]:
                        sub_started = time.monotonic()
                        try:
                            fd_data = VENDOR_METHODS["get_fundamentals"][vendor](ticker, curr_date)
                            if not isinstance(fd_data, NormalizedFinancialData):
                                fd_data = normalize_financial_result(fd_data, source=vendor)
                            val = validate_financial_result(fd_data, curr_date)
                            if not val.is_valid:
                                log_financial_audit(ticker, vendor, "get_fundamentals", "invalid", fd_data, val.detail)
                                raise NoUsableFinancialDataError(ticker, "fundamentals", val.detail)
                            record_financial_subcall(
                                "get_fundamentals", sub_started, "available", result=fd_data
                            )
                        except Exception as e:
                            record_financial_subcall(
                                "get_fundamentals", sub_started, "unavailable", error=e,
                                result=fd_data,
                            )
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
                    record_attempt(
                        vendor, "available", started, attempt=attempt,
                        selected=True, result=data_dict.get(method),
                    )
                    reconciled = True
                    break

                except VendorRateLimitError as e:
                    record_attempt(vendor, "rate_limited", started, e, attempt=attempt)
                    continue
                except VendorNotConfiguredError as e:
                    record_attempt(vendor, "not_configured", started, e, attempt=attempt)
                    if first_error is None:
                        first_error = e
                    continue
                except (NoMarketDataError, NoUsableFinancialDataError) as e:
                    record_attempt(vendor, "no_data", started, e, attempt=attempt)
                    last_no_data = e
                    continue
                except Exception as e:
                    record_attempt(vendor, "unavailable", started, e, attempt=attempt)
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
    for attempt, vendor in enumerate(vendor_chain, start=1):
        vendor_impl = VENDOR_METHODS[method][vendor]
        impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl

        started = time.monotonic()
        try:
            result = impl_func(*args, **kwargs)
            normalized_result = result
            if method == "get_indicators":
                indicator = str(args[1])
                reference_close = None
                symbol, curr_date = str(args[0]), str(args[2])
                end = datetime.strptime(curr_date, "%Y-%m-%d")
                lookback = max(int(args[3]), 30)
                start = (end - timedelta(days=lookback)).strftime("%Y-%m-%d")
                raw_ohlcv = route_to_vendor("get_stock_data", symbol, start, curr_date)
                expected_latest_date = latest_verified_ohlcv_date(
                    raw_ohlcv, curr_date
                )
                if indicator_requires_close(indicator):
                    reference_close = latest_verified_close(raw_ohlcv, curr_date)
                normalized = normalize_indicator_result(result, indicator, str(args[2]))
                validation = validate_indicator_result(
                    normalized,
                    reference_close=reference_close,
                    expected_latest_date=expected_latest_date,
                )
            elif method == "get_social_posts":
                try:
                    normalized_result = validate_social_feed(
                        result, str(args[1]), str(args[2])
                    )
                except (TypeError, ValueError) as exc:
                    raise NoMarketDataError(str(args[0]), detail=str(exc)) from exc
                validation = type("Validation", (), {"is_valid": True, "detail": ""})()
            elif method in {"get_news", "get_global_news"}:
                from .evidence_models import validate_news_feed
                try:
                    normalized_result = validate_news_feed(
                        result,
                        symbol=str(args[0]) if method == "get_news" else None,
                    )
                except (TypeError, ValueError) as exc:
                    raise NoMarketDataError(str(args[0]), detail=str(exc)) from exc
                validation = type("Validation", (), {"is_valid": True, "detail": ""})()
            elif method == "get_macro_indicators":
                from .evidence_models import validate_macro_series
                try:
                    normalized_result = validate_macro_series(result)
                except (TypeError, ValueError) as exc:
                    raise NoMarketDataError(str(args[0]), detail=str(exc)) from exc
                validation = type("Validation", (), {"is_valid": True, "detail": ""})()
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
                record_attempt(
                    vendor, "invalid", started, error, attempt=attempt,
                    result=normalized_result,
                )
                last_no_data = error
                logger.warning(
                    "Vendor %r returned invalid data for %s (%s); trying next vendor.",
                    vendor, method, validation.detail,
                )
                continue
            record_attempt(
                vendor, "available", started, attempt=attempt,
                selected=True, result=normalized_result,
            )
            return normalized_result
        except VendorRateLimitError as e:
            record_attempt(vendor, "rate_limited", started, e, attempt=attempt)
            logger.warning("Vendor %r rate-limited for %s; trying next vendor.", vendor, method)
            continue
        except VendorNotConfiguredError as e:
            record_attempt(vendor, "not_configured", started, e, attempt=attempt)
            logger.warning("Vendor %r not configured for %s; trying next vendor.", vendor, method)
            if first_error is None:
                first_error = e
            continue
        except NoMarketDataError as e:
            record_attempt(vendor, "no_data", started, e, attempt=attempt)
            last_no_data = e
            continue
        except Exception as e:
            record_attempt(vendor, "unavailable", started, e, attempt=attempt)
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
        if method in {
            "get_stock_data", "get_indicators", "get_social_posts",
            "get_news", "get_global_news", "get_macro_indicators",
        } | FINANCIAL_METHODS:
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


def _safe_audit_arguments(args, kwargs) -> str:
    """Serialize call parameters while excluding secret-like keys."""
    secret_markers = ("key", "token", "secret", "password", "cookie", "auth")

    def clean(value):
        if isinstance(value, dict):
            return {
                str(key): ("[REDACTED]" if any(m in str(key).lower() for m in secret_markers) else clean(item))
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [clean(item) for item in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    return json.dumps({"args": clean(args), "kwargs": clean(kwargs)}, ensure_ascii=False)


def _vendor_audit_metadata(method: str, args: tuple, category: str) -> dict[str, str | None]:
    agent_by_category = {
        "core_stock_apis": "Market Analyst",
        "technical_indicators": "Market Analyst",
        "fundamental_data": "Fundamentals Analyst",
        "news_data": "News Analyst",
        "macro_data": "News Analyst",
        "prediction_markets": "News Analyst",
        "social_data": "Sentiment Analyst",
    }
    metadata = {
        "agent": agent_by_category.get(category),
        "symbol": str(args[0]) if args else None,
        "calculation_start": None,
        "requested_end": None,
    }
    if method == "get_stock_data" and len(args) >= 3:
        metadata["calculation_start"] = str(args[1])
        metadata["requested_end"] = str(args[2])
    elif method == "get_indicators" and len(args) >= 4:
        end = datetime.strptime(str(args[2]), "%Y-%m-%d")
        from .indicator_requirements import indicator_calculation_lookback_days

        days = indicator_calculation_lookback_days(str(args[1]), int(args[3]))
        metadata["calculation_start"] = (end - timedelta(days=days)).strftime("%Y-%m-%d")
        metadata["requested_end"] = str(args[2])
    return metadata


def _latest_date_in_result(result: object) -> str | None:
    if result is None:
        return None
    text = str(result)
    dates = re.findall(r"(?m)^\s*(\d{4}-\d{2}-\d{2})(?=[:,])", text)
    if not dates:
        dates = re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    return max(dates) if dates else None


def _record_vendor_verification(
    vendor,
    category,
    method,
    status,
    source,
    started,
    error=None,
    *,
    call_id=None,
    attempt=1,
    selected=False,
    arguments_json=None,
    result=None,
    audit_metadata=None,
):
    """Update health telemetry and append mandatory run-scoped audit evidence."""
    health_record = None
    try:
        from .vendor_verification import vendor_verification_store

        health_record = vendor_verification_store.record(
            vendor=vendor,
            category=category,
            method=method,
            status=status,
            source=source,
            detail=str(error) if error else None,
            latency_ms=round((time.monotonic() - started) * 1000),
        )
    except Exception as exc:
        logger.debug("Could not update latest vendor health status: %s", exc)

    if source == "analysis" and call_id:
        from tradingagents.runtime.audit_context import current_run_id
        from tradingagents.runtime.history import history_store

        run_id = current_run_id()
        if run_id:
            finished = datetime.now(timezone.utc)
            latency_ms = round((time.monotonic() - started) * 1000)
            summary = None
            result_hash = None
            if result is not None:
                rendered = str(result)
                summary = rendered[:500]
                result_hash = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
            # Deliberately not swallowed: an analysis without its immutable
            # provenance ledger must not continue to an executable report.
            history_store.add_vendor_call({
                "run_id": run_id,
                "call_id": call_id,
                "attempt": attempt,
                "category": category,
                "method": method,
                "vendor": vendor,
                "agent": (audit_metadata or {}).get("agent"),
                "symbol": (audit_metadata or {}).get("symbol"),
                "status": status,
                "selected": selected,
                "arguments_json": arguments_json,
                "latency_ms": latency_ms,
                "error_type": type(error).__name__ if error else None,
                "error_detail": str(error) if error else None,
                "result_summary": summary,
                "result_hash": result_hash,
                "calculation_start": (audit_metadata or {}).get("calculation_start"),
                "requested_end": (audit_metadata or {}).get("requested_end"),
                "data_latest_date": _latest_date_in_result(result),
                "started_at": (finished - timedelta(milliseconds=latency_ms)).isoformat(),
                "finished_at": finished.isoformat(),
            })
    return health_record


def verify_vendor(vendor: str, category: str):
    """Run one direct, lightweight capability request without fallback."""
    now = datetime.now(timezone.utc).date()
    probes = {
        "core_stock_apis": ("get_stock_data", ("AAPL", str(now - timedelta(days=10)), str(now))),
        "technical_indicators": ("get_indicators", ("AAPL", "rsi", str(now), 30)),
        "fundamental_data": ("get_fundamentals", ("AAPL",)),
        "news_data": ("get_news", ("AAPL", str(now - timedelta(days=7)), str(now))),
        "social_data": ("get_social_posts", ("AAPL", str(now - timedelta(days=7)), str(now))),
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
