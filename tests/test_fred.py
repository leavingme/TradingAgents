"""FRED macro vendor: alias resolution, configuration errors, output formatting,
missing-value handling, lookahead-safe windowing, and router integration.

All API access is mocked, so these run without a network connection or a key.
"""
import copy
import unittest
from unittest import mock

import pytest

import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config
from tradingagents.dataflows import fred, interface
from tradingagents.dataflows.config import set_config

# A small, stable set of observations to format against.
_META = {
    "seriess": [
        {
            "title": "Unemployment Rate",
            "units_short": "%",
            "frequency": "Monthly",
            "seasonal_adjustment_short": "SA",
        }
    ]
}
_OBS = {
    "observations": [
        {"date": "2025-06-01", "value": "4.1"},
        {"date": "2025-07-01", "value": "4.3"},
        {"date": "2025-08-01", "value": "."},   # missing -> skipped
        {"date": "2025-09-01", "value": "4.4"},
    ]
}


def _request_stub(meta=_META, obs=_OBS):
    """Build a _request replacement that dispatches on the endpoint path."""
    def _impl(path, params):
        if path == "series":
            return meta
        if path == "series/observations":
            return obs
        raise AssertionError(f"unexpected FRED path: {path}")
    return _impl


@pytest.mark.unit
class FredResolutionTests(unittest.TestCase):
    def test_alias_maps_to_series_id(self):
        self.assertEqual(fred._resolve_series_id("cpi"), "CPIAUCSL")
        self.assertEqual(fred._resolve_series_id("unemployment"), "UNRATE")

    def test_alias_is_case_and_separator_insensitive(self):
        self.assertEqual(fred._resolve_series_id("Fed Funds Rate"), "FEDFUNDS")
        self.assertEqual(fred._resolve_series_id("10y-treasury"), "DGS10")

    def test_unknown_alias_is_treated_as_raw_series_id(self):
        # Power users can pass any FRED series ID; we uppercase by convention.
        self.assertEqual(fred._resolve_series_id("dgs30"), "DGS30")
        self.assertEqual(fred._resolve_series_id("MyCustomSeries"), "MYCUSTOMSERIES")

    def test_descriptive_phrase_is_rejected(self):
        # An LLM phrase (spaces / too long) is not a series ID — reject up front
        # with guidance rather than 400ing the API.
        for bad in ("bank of japan rate", "the unemployment number", "X" * 31):
            with self.assertRaises(ValueError):
                fred._resolve_series_id(bad)

    def test_get_macro_data_raises_on_bad_indicator(self):
        with self.assertRaisesRegex(fred.NoMarketDataError, "not a known macro alias"):
            fred.get_macro_data("bank of japan rate", "2026-01-01")


@pytest.mark.unit
class FredConfigTests(unittest.TestCase):
    def test_missing_key_raises_not_configured(self):
        with mock.patch.dict("os.environ", {}, clear=True), \
                self.assertRaises(fred.FredNotConfiguredError):
            fred.get_api_key()

    def test_not_configured_is_a_value_error(self):
        # Routing relies on this subclassing for "vendor unavailable" handling.
        self.assertTrue(issubclass(fred.FredNotConfiguredError, ValueError))


@pytest.mark.unit
class FredFormattingTests(unittest.TestCase):
    def test_report_has_header_latest_change_and_table(self):
        with mock.patch.object(fred, "_request", side_effect=_request_stub()):
            out = fred.get_macro_data("unemployment", "2025-09-30", 365)
        self.assertEqual(out.series_id, "UNRATE")
        self.assertEqual(out.title, "Unemployment Rate")
        self.assertEqual(out.units, "%")
        self.assertEqual(out.frequency, "Monthly (SA)")
        self.assertEqual(out.observations[-1].value, 4.4)
        self.assertTrue(out.observations[-1].source_id.startswith("macro_"))

    def test_missing_value_is_skipped(self):
        with mock.patch.object(fred, "_request", side_effect=_request_stub()):
            out = fred.get_macro_data("unemployment", "2025-09-30", 365)
        # the "." observation must not appear as a row
        self.assertNotIn("2025-08-01", [item.observed_at for item in out.observations])

    def test_empty_window_raises_no_data(self):
        empty = {"observations": []}
        with mock.patch.object(fred, "_request", side_effect=_request_stub(obs=empty)), \
                self.assertRaisesRegex(fred.NoMarketDataError, "no observations"):
            fred.get_macro_data("unemployment", "2025-09-30", 30)

    def test_unknown_series_raises_no_data(self):
        no_series = {"seriess": []}
        with mock.patch.object(fred, "_request", side_effect=_request_stub(meta=no_series)), \
                self.assertRaisesRegex(fred.NoMarketDataError, "not found"):
            fred.get_macro_data("totally_unknown_xyz", "2025-09-30", 30)

    def test_long_series_is_truncated_but_change_uses_full_range(self):
        # Build > MAX_ROWS observations deterministically.
        obs = {
            "observations": [
                {"date": f"2025-01-{(i % 28) + 1:02d}", "value": str(i)}
                for i in range(fred.MAX_ROWS + 10)
            ]
        }
        with mock.patch.object(fred, "_request", side_effect=_request_stub(obs=obs)):
            out = fred.get_macro_data("unemployment", "2025-12-31", 365)
        from tradingagents.dataflows.evidence_models import render_macro_series
        rendered = render_macro_series(out)
        body_rows = [ln for ln in rendered.splitlines() if ln.startswith("| macro_")]
        self.assertEqual(len(body_rows), fred.MAX_ROWS)

    def test_window_is_lookahead_safe(self):
        # observation_end must equal curr_date so a past date never pulls future data.
        captured = {}

        def _capture(path, params):
            captured[path] = params
            return _META if path == "series" else _OBS

        with mock.patch.object(fred, "_request", side_effect=_capture):
            fred.get_macro_data("unemployment", "2025-09-30", 90)
        obs_params = captured["series/observations"]
        self.assertEqual(obs_params["observation_end"], "2025-09-30")
        self.assertEqual(obs_params["observation_start"], "2025-07-02")  # 90d back


@pytest.mark.unit
class FredRoutingTests(unittest.TestCase):
    def setUp(self):
        config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)

    def tearDown(self):
        config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)

    def test_macro_category_routes_to_fred(self):
        self.assertEqual(
            interface.get_category_for_method("get_macro_indicators"), "macro_data"
        )
        set_config({"data_vendors": {"macro_data": "fred"}})
        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_macro_indicators": {"fred": lambda *a, **k: fred.MacroSeries(
                series_id="CPI", title="CPI", units="Index", frequency="Monthly",
                requested_start="2025-06-01", requested_end="2026-06-01",
                observations=(fred.MacroObservation(
                    source_id=fred.macro_source_id("CPI", "2026-05-01"),
                    series_id="CPI", title="CPI",
                    units="Index", frequency="Monthly", observed_at="2026-05-01",
                    value=100.0, vendor="fred",
                ),),
            )}},
            clear=False,
        ):
            out = interface.route_to_vendor("get_macro_indicators", "cpi", "2026-06-01", 365)
        self.assertEqual(out.series_id, "CPI")

    def test_not_configured_remains_a_typed_failure(self):
        # Macro is decision evidence: missing credentials must never be returned
        # as a successful-looking text sentinel.
        set_config({"data_vendors": {"macro_data": "fred"}})

        def _unconfigured(*a, **k):
            raise fred.FredNotConfiguredError("FRED_API_KEY not set")

        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_macro_indicators": {"fred": _unconfigured}},
            clear=False,
        ), self.assertRaises(fred.FredNotConfiguredError):
            interface.route_to_vendor("get_macro_indicators", "cpi", "2026-06-01", 365)


if __name__ == "__main__":
    unittest.main()
