import copy
import json
from unittest import mock

import pytest

import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config
from tradingagents.dataflows import interface, longbridge_mcp
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import NoUsableFinancialDataError
from tradingagents.dataflows.financial_validation import (
    FINANCIAL_EVIDENCE_SCHEMA,
    DerivedFinancialMetric,
    FinancialMetric,
    NormalizedFinancialData,
    derive_financial_metrics,
    normalize_financial_result,
    render_financial_data,
    render_financial_evidence,
    validate_financial_result,
)
from tradingagents.dataflows.longbridge_financial_adapter import (
    adapt_longbridge_financial_report,
)


VALID_STATEMENT = """# IS for 0700.HK

## Revenue
  Revenue(HKD): 222732641073.4178  [Q1 2026]  yoy=15.5
## ROE
  ROE: 20.3672  [Q1 2026]
"""


@pytest.fixture(autouse=True)
def reset_config():
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    yield
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


@pytest.mark.unit
def test_legacy_text_metrics_without_full_context_are_invalid():
    data = normalize_financial_result(VALID_STATEMENT, "longbridge_mcp")
    assert len(data.metrics) == 1
    revenue = data.metrics[0]
    assert revenue.currency == "HKD"
    assert revenue.unit == "HKD"
    assert revenue.period_type == "quarterly"
    assert data.excluded_metrics == ("ROE",)
    result = validate_financial_result(data)
    assert not result.is_valid
    assert "XBRL-style context" in result.detail


@pytest.mark.unit
def test_compact_financial_evidence_preserves_every_verified_observation():
    def statement(kind: str, context_type: str) -> NormalizedFinancialData:
        metrics = []
        for metric_index in range(12):
            for quarter in range(1, 5):
                metrics.append(FinancialMetric(
                    metric=f"{kind} metric {metric_index}",
                    value=float(metric_index * 100 + quarter),
                    currency="USD",
                    unit="USD",
                    period=f"Q{quarter} 2026",
                    period_type="quarterly",
                    source="mock_vendor",
                    period_start=(
                        f"2026-0{quarter}-01" if context_type == "duration" else None
                    ),
                    period_end=f"2026-0{quarter}-28",
                    context_type=context_type,
                    source_field=f"field_{metric_index}",
                ))
        return NormalizedFinancialData(metrics=tuple(metrics), source_text="")

    income = statement("income", "duration")
    balance = statement("balance", "instant")
    cashflow = statement("cashflow", "duration")
    derived = [DerivedFinancialMetric(
        metric="net_margin",
        value=20.0,
        unit="percent",
        period="Q1 2026",
        period_type="quarterly",
        formula="net_income / revenue * 100",
        inputs={"net_income": 20.0, "revenue": 100.0},
    )]

    rendered = render_financial_evidence(
        income_statement=income,
        balance_sheet=balance,
        cashflow=cashflow,
        fundamentals=None,
        derived_metrics=derived,
    )
    payload = json.loads(rendered)

    assert payload["schema"] == FINANCIAL_EVIDENCE_SCHEMA
    assert payload["status"] == "verified_and_reconciled"
    for name, source in (
        ("income_statement", income),
        ("balance_sheet", balance),
        ("cashflow", cashflow),
    ):
        compact = payload["statements"][name]
        assert compact["verified_metric_count"] == len(source.metrics)
        observations = [
            observation
            for series in compact["series"]
            for observation in series[-1]
        ]
        assert len(observations) == len(source.metrics)
        assert sorted(float(row[-1]) for row in observations) == sorted(
            metric.value for metric in source.metrics
        )
    verbose_size = sum(
        len(render_financial_data(source, []))
        for source in (income, balance, cashflow)
    )
    assert len(rendered) < verbose_size * 0.6


@pytest.mark.unit
def test_monetary_metric_without_currency_is_invalid():
    data = normalize_financial_result("  Revenue: 1000  [Q1 2026]", "vendor")
    result = validate_financial_result(data)
    assert not result.is_valid
    assert "currency" in result.detail


@pytest.mark.unit
def test_metric_without_period_is_invalid():
    data = normalize_financial_result("  Revenue(HKD): 1000", "vendor")
    result = validate_financial_result(data)
    assert not result.is_valid
    assert "no structured metrics" in result.detail


@pytest.mark.unit
def test_ambiguous_derived_metric_is_excluded():
    data = normalize_financial_result(
        "  Operating profit/operating cash flow: 66.47  [Q1 2026]",
        "vendor",
    )
    assert not data.metrics
    assert data.excluded_metrics == ("Operating profit/operating cash flow",)


@pytest.mark.unit
def test_margins_are_recomputed_with_formula_and_inputs():
    payload = """
  Revenue(HKD): 1000  [Q1 2026]
  Gross profit(HKD): 600  [Q1 2026]
  Operating profit(HKD): 300  [Q1 2026]
  Net income(HKD): 200  [Q1 2026]
  Net margin: 99  [Q1 2026]
"""
    data = normalize_financial_result(payload, "vendor")
    derived = {metric.metric: metric for metric in derive_financial_metrics(data)}
    assert derived["gross_margin"].value == 60
    assert derived["operating_margin"].value == 30
    assert derived["net_margin"].value == 20
    assert derived["net_margin"].formula == "net_income / revenue * 100"
    assert "Net margin" in data.excluded_metrics


@pytest.mark.unit
def test_longbridge_raw_json_maps_directly_to_domain_model():
    raw = {
        "report": "qf",
        "list": {
            "IS": {
                "indicators": [{
                    "title": "营业收入",
                    "accounts": [{
                        "name": "营业收入(HKD)",
                        "values": [{
                            "value": "1000",
                            "period": "Q1 2026",
                            "fp_end": "1774886400",
                        }],
                    }],
                }],
            },
        },
    }
    data = adapt_longbridge_financial_report(raw, "IS", "longbridge_mcp", "700.HK")
    assert data.raw_payload is raw
    assert data.source_text == ""
    assert data.metrics[0].metric == "营业收入"
    assert data.metrics[0].currency == "HKD"
    assert data.metrics[0].period_type == "quarterly"


@pytest.mark.unit
def test_vendor_derived_fact_is_preserved_as_unverified_with_context():
    raw = {
        "list": {
            "IS": {
                "indicators": [{
                    "title": "ROE",
                    "accounts": [{
                        "field": "ROE",
                        "name": "ROE",
                        "percent": True,
                        "tip": "ROE=EPS/average BPS",
                        "values": [{
                            "value": "20.3672",
                            "period": "Q1 2026",
                            "fp_end": "1774886400",
                        }],
                    }],
                }],
            },
        },
    }
    data = adapt_longbridge_financial_report(raw, "IS", "longbridge_mcp", "700.HK")
    assert not data.metrics
    assert len(data.unverified_facts) == 1
    fact = data.unverified_facts[0]
    assert fact.metric == "ROE"
    assert fact.value == 20.3672
    assert fact.period == "Q1 2026"
    assert fact.period_end == "2026-03-31"
    assert fact.definition == "ROE=EPS/average BPS"
    assert fact.status == "unverified"


@pytest.mark.unit
def test_financial_fact_after_analysis_date_is_invalid():
    raw = {
        "report": "qf",
        "list": {"IS": {"indicators": [{
            "accounts": [{
                "field": "Revenue",
                "name": "Revenue(HKD)",
                "values": [{
                    "value": "1000",
                    "period": "Q1 2026",
                    "fp_end": "1774886400",
                }],
            }],
        }]}},
    }
    data = adapt_longbridge_financial_report(raw, "IS", "longbridge_mcp", "700.HK")
    result = validate_financial_result(data, "2026-03-01")
    assert not result.is_valid
    assert "after the analysis date" in result.detail


@pytest.mark.unit
def test_invalid_financial_vendor_falls_back_and_returns_canonical_json():
    set_config({"data_vendors": {"fundamental_data": "primary,fallback"}})
    invalid = "  Revenue: 1000  [Q1 2026]"
    valid_raw = {
        "report": "qf",
        "list": {"IS": {"indicators": [{
            "accounts": [{
                "field": "Revenue",
                "name": "Revenue(HKD)",
                "values": [{
                    "value": "1000",
                    "period": "Q1 2026",
                    "fp_end": "1774886400",
                }],
            }],
        }]}},
    }
    valid_data = adapt_longbridge_financial_report(
        valid_raw, "IS", "fallback", "700.HK"
    )
    with mock.patch.dict(
        interface.VENDOR_METHODS,
        {"get_income_statement": {
            "primary": lambda *args: invalid,
            "fallback": lambda *args: valid_data,
        }},
        clear=False,
    ):
        result = interface.route_to_vendor(
            "get_income_statement", "0700.HK", "quarterly", "2026-07-10"
        )
    parsed = json.loads(result)
    assert parsed["status"] == "verified"
    assert parsed["metrics"][0]["currency"] == "HKD"


@pytest.mark.unit
def test_financial_llm_renderer_uses_compact_lossless_json():
    data = normalize_financial_result(
        "  Revenue(HKD): 1000  [Q1 2026]",
        "vendor",
    )
    rendered = render_financial_data(data, [])
    assert "\n" not in rendered
    parsed = json.loads(rendered)
    assert parsed["status"] == "verified"
    assert parsed["metrics"][0]["value"] == 1000.0


@pytest.mark.unit
def test_all_invalid_financial_vendors_raise_hard_failure():
    set_config({"data_vendors": {"fundamental_data": "primary,fallback"}})
    with mock.patch.dict(
        interface.VENDOR_METHODS,
        {"get_income_statement": {
            "primary": lambda *args: "  Revenue: 1000  [Q1 2026]",
            "fallback": lambda *args: "  Revenue(HKD): 1000",
        }},
        clear=False,
    ):
        with pytest.raises(NoUsableFinancialDataError):
            interface.route_to_vendor(
                "get_income_statement", "0700.HK", "quarterly", "2026-07-10"
            )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("function_name", "expected_kind"),
    [
        ("get_income_statement", "IS"),
        ("get_balance_sheet", "BS"),
        ("get_cashflow", "CF"),
    ],
)
def test_mcp_statement_kind_is_independent_from_frequency(monkeypatch, function_name, expected_kind):
    calls = []

    class Client:
        def call_tool(self, tool, args):
            calls.append(args)
            return {"list": {expected_kind: {"indicators": []}}}

    monkeypatch.setattr(longbridge_mcp, "_client", lambda: Client())
    monkeypatch.setattr(longbridge_mcp, "_resolve_tool", lambda client, capability: capability)
    getattr(longbridge_mcp, function_name)("0700.HK", "quarterly", "2026-07-10")
    assert calls[0]["kind"] == expected_kind
    assert calls[0]["report_type"] == "qf"
