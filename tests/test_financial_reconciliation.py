import json
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from unittest import mock

from tradingagents.dataflows import interface
from tradingagents.dataflows.errors import NoUsableFinancialDataError
from tradingagents.dataflows.financial_validation import (
    FinancialMetric,
    NormalizedFinancialData,
    UnverifiedFinancialFact,
    reconcile_financials,
    compute_derived_metrics,
    log_financial_audit,
    render_financial_data,
)


@pytest.fixture
def mock_financial_data():
    # Helper to construct NormalizedFinancialData
    def _create(metrics_dict, entity_metadata=None, unverified_facts=None):
        metrics = []
        for period, values in metrics_dict.items():
            for metric_name, val in values.items():
                metrics.append(FinancialMetric(
                    metric=metric_name,
                    value=float(val),
                    currency="USD",
                    unit="USD",
                    period=period,
                    period_type="quarterly" if "Q" in period else "annual",
                    source="mock",
                    period_start="2026-01-01" if "Q" in period else None,
                    period_end="2026-03-31" if "Q" in period else None,
                    context_type="duration" if metric_name != "Total Assets" and metric_name != "Total Liabilities" and metric_name != "Total Equity" and metric_name != "Cash and Equivalents" else "instant",
                ))
        return NormalizedFinancialData(
            metrics=tuple(metrics),
            source_text="raw",
            raw_payload={"mock": "payload"},
            entity_metadata=entity_metadata or {"symbol": "MOCK"},
            unverified_facts=tuple(unverified_facts) if unverified_facts else (),
        )
    return _create


@pytest.mark.unit
def test_period_consistency_check_raises_on_mismatch(mock_financial_data):
    # IS has Q1 2026, but BS has only Q4 2025 -> Period inconsistency
    is_data = mock_financial_data({"Q1 2026": {"Revenue": 1000, "Net Income": 200}})
    bs_data = mock_financial_data({"Q4 2025": {"Total Assets": 5000, "Total Liabilities": 3000, "Total Equity": 2000}})
    cf_data = mock_financial_data({"Q1 2026": {"Operating Cash Flow": 300, "Net Income": 200, "Cash and Equivalents": 1000}})

    with mock.patch.dict(
        interface.VENDOR_METHODS,
        {
            "get_income_statement": {"mock_vendor": lambda *a, **kw: is_data},
            "get_balance_sheet": {"mock_vendor": lambda *a, **kw: bs_data},
            "get_cashflow": {"mock_vendor": lambda *a, **kw: cf_data},
        },
        clear=False,
    ), mock.patch("tradingagents.dataflows.interface.get_vendor", return_value="mock_vendor"):
        with pytest.raises(NoUsableFinancialDataError) as exc_info:
            interface.route_to_vendor("get_income_statement", "MOCK", "quarterly", "2026-07-10")
        assert "Period inconsistency" in str(exc_info.value)


@pytest.mark.unit
def test_cross_statement_reconciliation_balance_sheet_mismatch(mock_financial_data):
    # Assets (50000) != Liabilities (3000) + Equity (1000) -> BS Equation Mismatch
    is_data = mock_financial_data({"Q1 2026": {"Revenue": 1000, "Net Income": 200}})
    bs_data = mock_financial_data({"Q1 2026": {"Total Assets": 50000, "Total Liabilities": 3000, "Total Equity": 1000}})
    cf_data = mock_financial_data({"Q1 2026": {"Operating Cash Flow": 300, "Net Income": 200, "Cash and Equivalents": 1000}})

    with mock.patch.dict(
        interface.VENDOR_METHODS,
        {
            "get_income_statement": {"mock_vendor": lambda *a, **kw: is_data},
            "get_balance_sheet": {"mock_vendor": lambda *a, **kw: bs_data},
            "get_cashflow": {"mock_vendor": lambda *a, **kw: cf_data},
        },
        clear=False,
    ), mock.patch("tradingagents.dataflows.interface.get_vendor", return_value="mock_vendor"):
        with pytest.raises(NoUsableFinancialDataError) as exc_info:
            interface.route_to_vendor("get_income_statement", "MOCK", "quarterly", "2026-07-10")
        assert "Balance sheet equation failed" in str(exc_info.value)


@pytest.mark.unit
def test_cross_statement_reconciliation_net_income_mismatch(mock_financial_data):
    # IS Net Income (20000) != CF Net Income (150) -> Net Income Mismatch
    is_data = mock_financial_data({"Q1 2026": {"Revenue": 1000, "Net Income": 20000}})
    bs_data = mock_financial_data({"Q1 2026": {"Total Assets": 5000, "Total Liabilities": 3000, "Total Equity": 2000}})
    cf_data = mock_financial_data({"Q1 2026": {"Operating Cash Flow": 300, "Net Income": 150, "Cash and Equivalents": 1000}})

    with mock.patch.dict(
        interface.VENDOR_METHODS,
        {
            "get_income_statement": {"mock_vendor": lambda *a, **kw: is_data},
            "get_balance_sheet": {"mock_vendor": lambda *a, **kw: bs_data},
            "get_cashflow": {"mock_vendor": lambda *a, **kw: cf_data},
        },
        clear=False,
    ), mock.patch("tradingagents.dataflows.interface.get_vendor", return_value="mock_vendor"):
        with pytest.raises(NoUsableFinancialDataError) as exc_info:
            interface.route_to_vendor("get_income_statement", "MOCK", "quarterly", "2026-07-10")
        assert "Net income mismatch" in str(exc_info.value)


@pytest.mark.unit
def test_cross_statement_reconciliation_cash_mismatch(mock_financial_data):
    # CF Ending Cash (800) != BS Cash and Equivalents (10000) -> Cash Mismatch
    is_data = mock_financial_data({"Q1 2026": {"Revenue": 1000, "Net Income": 200}})
    bs_data = mock_financial_data({"Q1 2026": {"Total Assets": 5000, "Total Liabilities": 3000, "Total Equity": 2000, "Cash and Equivalents": 10000}})
    cf_data = mock_financial_data({"Q1 2026": {"Operating Cash Flow": 300, "Net Income": 200, "Cash and Equivalents": 800}})

    with mock.patch.dict(
        interface.VENDOR_METHODS,
        {
            "get_income_statement": {"mock_vendor": lambda *a, **kw: is_data},
            "get_balance_sheet": {"mock_vendor": lambda *a, **kw: bs_data},
            "get_cashflow": {"mock_vendor": lambda *a, **kw: cf_data},
        },
        clear=False,
    ), mock.patch("tradingagents.dataflows.interface.get_vendor", return_value="mock_vendor"):
        with pytest.raises(NoUsableFinancialDataError) as exc_info:
            interface.route_to_vendor("get_income_statement", "MOCK", "quarterly", "2026-07-10")
        assert "Cash balance mismatch" in str(exc_info.value)


@pytest.mark.unit
def test_run_scoped_financial_reconciliation_is_singleflight_across_tool_threads(
    mock_financial_data,
):
    is_data = mock_financial_data({
        "Q1 2026": {"Revenue": 1000, "Net Income": 200, "Operating Profit": 300}
    })
    bs_data = mock_financial_data({
        "Q1 2026": {
            "Total Assets": 5000,
            "Total Liabilities": 3000,
            "Total Equity": 2000,
            "Cash and Equivalents": 1000,
        }
    })
    cf_data = mock_financial_data({
        "Q1 2026": {
            "Operating Cash Flow": 300,
            "Net Income": 200,
            "Cash and Equivalents": 1000,
        }
    })
    fd_data = mock_financial_data({"Q1 2026": {"Revenue": 1000}})
    payloads = {
        "get_income_statement": is_data,
        "get_balance_sheet": bs_data,
        "get_cashflow": cf_data,
        "get_fundamentals": fd_data,
    }
    calls = {method: 0 for method in payloads}
    call_guard = threading.Lock()
    start = threading.Barrier(4)
    audit_records = []

    def vendor(method):
        def fetch(*args, **kwargs):
            with call_guard:
                calls[method] += 1
            time.sleep(0.02)
            return payloads[method]
        return fetch

    vendor_methods = {
        method: {"mock_vendor": vendor(method)} for method in payloads
    }

    def invoke(method):
        start.wait()
        if method == "get_fundamentals":
            return interface.route_to_vendor(method, "MOCK", None)
        return interface.route_to_vendor(method, "MOCK", "quarterly", None)

    with interface._financial_cache_condition:
        interface._shared_financial_cache.clear()
        interface._shared_financial_inflight.clear()
    with mock.patch.dict(interface.VENDOR_METHODS, vendor_methods, clear=False), \
         mock.patch("tradingagents.dataflows.interface.get_vendor", return_value="mock_vendor"), \
         mock.patch(
             "tradingagents.runtime.audit_context.current_run_id",
             return_value="run-financial-singleflight",
         ), \
         mock.patch(
             "tradingagents.dataflows.interface._record_vendor_verification",
             side_effect=lambda *args, **kwargs: audit_records.append((args, kwargs)),
         ):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(invoke, payloads))

    assert all(isinstance(result, str) and result for result in results)
    assert calls == {method: 1 for method in payloads}
    cache_hits = [
        (args, kwargs) for args, kwargs in audit_records
        if len(args) > 3 and args[3] == "cache_hit"
    ]
    assert len(cache_hits) == 3
    assert all(kwargs.get("selected") is True for _, kwargs in cache_hits)


@pytest.mark.unit
def test_get_fundamentals_second_argument_is_propagated_as_point_in_time_date(
    mock_financial_data,
):
    payloads = {
        "get_income_statement": mock_financial_data({
            "Q1 2026": {"Revenue": 1000, "Net Income": 200}
        }),
        "get_balance_sheet": mock_financial_data({
            "Q1 2026": {
                "Total Assets": 5000,
                "Total Liabilities": 3000,
                "Total Equity": 2000,
                "Cash and Equivalents": 1000,
            }
        }),
        "get_cashflow": mock_financial_data({
            "Q1 2026": {
                "Operating Cash Flow": 300,
                "Net Income": 200,
                "Cash and Equivalents": 1000,
            }
        }),
        "get_fundamentals": mock_financial_data({"Q1 2026": {"Revenue": 1000}}),
    }
    received = {method: [] for method in payloads}

    def vendor(method):
        def fetch(*args, **kwargs):
            received[method].append(args)
            return payloads[method]
        return fetch

    vendor_methods = {
        method: {"mock_vendor": vendor(method)} for method in payloads
    }
    vendor_methods["get_stock_data"] = {
        "mock_vendor": lambda *args, **kwargs: "Date,Close\n2026-07-10,100.0\n"
    }
    with interface._financial_cache_condition:
        interface._shared_financial_cache.clear()
        interface._shared_financial_inflight.clear()
    with mock.patch.dict(interface.VENDOR_METHODS, vendor_methods, clear=False), \
         mock.patch("tradingagents.dataflows.interface.get_vendor", return_value="mock_vendor"), \
         mock.patch(
             "tradingagents.runtime.audit_context.current_run_id",
             return_value="run-financial-cutoff",
         ), \
         mock.patch(
             "tradingagents.dataflows.interface._record_vendor_verification",
             return_value=None,
         ):
        result = interface.route_to_vendor(
            "get_fundamentals", "MOCK", "2026-07-10"
        )

    assert result
    assert received["get_income_statement"] == [("MOCK", "quarterly", "2026-07-10")]
    assert received["get_balance_sheet"] == [("MOCK", "quarterly", "2026-07-10")]
    assert received["get_cashflow"] == [("MOCK", "quarterly", "2026-07-10")]
    assert received["get_fundamentals"] == [("MOCK", "2026-07-10")]


@pytest.mark.unit
def test_deterministic_derived_metrics_computation(mock_financial_data):
    is_data = mock_financial_data({"Q1 2026": {"Revenue": 1000, "Net Income": 200, "Operating Profit": 300, "EPS": 2.0}})
    bs_data = mock_financial_data({"Q1 2026": {"Total Assets": 5000, "Total Liabilities": 3000, "Total Equity": 2000, "Cash and Equivalents": 1000, "Short-term Debt": 200, "Long-term Debt": 300}})
    cf_data = mock_financial_data({"Q1 2026": {"Operating Cash Flow": 300, "Net Income": 200, "Cash and Equivalents": 1000, "Depreciation & Amortization": 50}})
    fd_data = mock_financial_data({}, unverified_facts=[
        UnverifiedFinancialFact(metric="mktcap", value=10000.0, currency="USD", unit="USD", period=None, period_type=None, period_end=None, source="mock", source_field="mktcap", definition=None, reason="unverified")
    ])

    derived = compute_derived_metrics(
        "Q1 2026",
        "quarterly",
        is_data,
        bs_data,
        cf_data,
        fd_data,
        share_price=100.0
    )

    metrics_map = {m.metric: m for m in derived}

    # 1. ROE = 200 / 2000 * 100 = 10%
    assert metrics_map["ROE"].value == 10.0
    assert metrics_map["ROE"].formula == "Net Income / Total Equity * 100"
    assert metrics_map["ROE"].inputs == {"net_income": 200.0, "total_equity": 2000.0}

    # 2. ROA = 200 / 5000 * 100 = 4%
    assert metrics_map["ROA"].value == 4.0
    assert metrics_map["ROA"].inputs == {"net_income": 200.0, "total_assets": 5000.0}

    # 3. Net Cash = 1000 - (200 + 300) = 500
    assert metrics_map["Net Cash"].value == 500.0
    assert metrics_map["Net Cash"].inputs == {"cash_and_equivalents": 1000.0, "short_term_debt": 200.0, "long_term_debt": 300.0}

    # 4. EV/EBITDA
    # EBITDA = 300 + 50 = 350
    # EV = 10000 + 500 - 1000 = 9500
    # EV/EBITDA = 9500 / 350 = 27.14
    assert round(metrics_map["EV/EBITDA"].value, 2) == round(9500.0 / 350.0, 2)
    assert metrics_map["EV/EBITDA"].formula == "(Market Cap + Short-term Debt + Long-term Debt - Cash) / (Operating Profit + Depreciation & Amortization)"


@pytest.mark.unit
def test_independent_audit_recording(mock_financial_data, tmp_path):
    # Set home dir to tmp_path to test file generation
    with mock.patch("pathlib.Path.home", return_value=tmp_path):
        is_data = mock_financial_data({"Q1 2026": {"Revenue": 1000, "Net Income": 200}})
        log_financial_audit("MOCK", "mock_vendor", "get_income_statement", "verified", is_data)

        audit_file = tmp_path / ".tradingagents" / "financial_audit.jsonl"
        assert audit_file.exists()

        with open(audit_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            assert len(lines) == 1
            entry = json.loads(lines[0])
            assert entry["symbol"] == "MOCK"
            assert entry["vendor"] == "mock_vendor"
            assert entry["status"] == "verified"
            assert entry["raw_payload"] == {"mock": "payload"}
            # check unverified fact count or structure
            assert "metrics" in entry
            assert len(entry["metrics"]) == 2
