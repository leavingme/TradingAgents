"""FRED macro vendor: alias resolution, configuration errors, output formatting,
missing-value handling, lookahead-safe windowing, and router integration.

All API access is mocked, so these run without a network connection or a key.
"""
import copy
from datetime import datetime, timezone
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


def _initial_releases(obs):
    return {"observations": [
        {**row, "realtime_start": row["date"]}
        for row in obs.get("observations", [])
    ]}


def _request_stub(meta=_META, obs=_OBS):
    """Build a _request replacement that dispatches on the endpoint path."""
    def _impl(path, params):
        if path == "series":
            return meta
        if path == "series/observations":
            return _initial_releases(obs) if params.get("output_type") == 4 else obs
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

    def test_http_error_never_exposes_api_key_or_request_url(self):
        response = mock.Mock(
            status_code=502,
            reason="Bad Gateway",
        )
        with mock.patch.dict("os.environ", {"FRED_API_KEY": "fake-secret-key"}), \
                mock.patch.object(fred.requests, "get", return_value=response), \
                self.assertRaises(fred.requests.HTTPError) as raised:
            fred._request("series", {"series_id": "GDPC1"})

        detail = str(raised.exception)
        self.assertIn("HTTP 502 Bad Gateway for series", detail)
        self.assertNotIn("fake-secret-key", detail)
        self.assertNotIn("api_key", detail)
        self.assertNotIn("https://", detail)

    def test_transport_error_never_forwards_prepared_url(self):
        upstream = fred.requests.ConnectionError(
            "failed for https://example.test?api_key=fake-secret-key"
        )
        with mock.patch.dict("os.environ", {"FRED_API_KEY": "fake-secret-key"}), \
                mock.patch.object(fred.requests, "get", side_effect=upstream), \
                self.assertRaises(fred.requests.RequestException) as raised:
            fred._request("series/observations", {"series_id": "DGS10"})

        detail = str(raised.exception)
        self.assertEqual(
            detail,
            "FRED transport failed for series/observations: ConnectionError",
        )
        self.assertNotIn("fake-secret-key", detail)
        self.assertNotIn("api_key", detail)

    def test_bad_request_keeps_safe_fred_error_message(self):
        response = mock.Mock(status_code=400)
        response.json.return_value = {"error_message": "unknown series id"}
        with mock.patch.dict("os.environ", {"FRED_API_KEY": "fake-secret-key"}), \
                mock.patch.object(fred.requests, "get", return_value=response), \
                self.assertRaisesRegex(ValueError, "unknown series id") as raised:
            fred._request("series", {"series_id": "UNKNOWN"})

        self.assertNotIn("fake-secret-key", str(raised.exception))


@pytest.mark.unit
class FredFormattingTests(unittest.TestCase):
    def test_live_vintage_uses_fred_calendar_across_utc_midnight(self):
        instant = datetime(2026, 7, 15, 2, 42, tzinfo=timezone.utc)
        self.assertEqual(fred._live_vintage_date(instant), "2026-07-14")

    def test_live_vintage_rejects_naive_time(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            fred._live_vintage_date(datetime(2026, 7, 15, 2, 42))

    def test_report_has_header_latest_change_and_table(self):
        with mock.patch.object(fred, "_request", side_effect=_request_stub()):
            out = fred.get_macro_data("unemployment", "2025-09-30", 365)
        self.assertEqual(out.series_id, "UNRATE")
        self.assertEqual(out.title, "Unemployment Rate")
        self.assertEqual(out.units, "%")
        self.assertEqual(out.frequency, "Monthly (SA)")
        self.assertEqual(out.observations[-1].value, 4.4)
        self.assertTrue(out.observations[-1].source_id.startswith("macro_"))
        self.assertEqual(out.vintage_date, "2025-09-30")
        self.assertEqual(out.observations[-1].published_at, "2025-09-01")
        self.assertEqual(out.observations[-1].revision_status, "initial")
        from tradingagents.dataflows.evidence_models import validate_macro_series
        with self.assertRaisesRegex(ValueError, "requested indicator"):
            validate_macro_series(
                out, expected_vendor="fred", expected_indicator="cpi"
            )

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
        captured = []

        def _capture(path, params):
            captured.append((path, params))
            if path == "series":
                return _META
            return _initial_releases(_OBS) if params.get("output_type") == 4 else _OBS

        with mock.patch.object(fred, "_request", side_effect=_capture):
            fred.get_macro_data("unemployment", "2025-09-30", 90)
        obs_params = next(
            params for path, params in captured
            if path == "series/observations" and "vintage_dates" in params
        )
        self.assertEqual(obs_params["observation_end"], "2025-09-30")
        self.assertEqual(obs_params["observation_start"], "2025-07-02")  # 90d back
        self.assertEqual(obs_params["vintage_dates"], "2025-09-30")

    def test_daily_initial_release_query_uses_observation_window(self):
        captured = []

        def _capture(path, params):
            captured.append((path, params))
            if path == "series":
                return _META
            return _initial_releases(_OBS) if params.get("output_type") == 4 else _OBS

        with mock.patch.object(fred, "_request", side_effect=_capture):
            fred.get_macro_data("vix", "2026-07-14", 365)

        release_requests = [
            params for path, params in captured
            if path == "series/observations" and params.get("output_type") == 4
        ]
        self.assertEqual(len(release_requests), 1)
        self.assertEqual(release_requests[0]["realtime_start"], "2025-07-14")
        self.assertEqual(release_requests[0]["realtime_end"], "2026-07-14")
        self.assertNotEqual(release_requests[0]["realtime_start"], "1776-07-04")

    def test_long_vintage_range_is_chunked_and_earliest_release_wins(self):
        observation = {"observations": [{"date": "2015-08-01", "value": "4.4"}]}
        captured_release_requests = []

        def _response(path, params):
            if path == "series":
                return _META
            if not params.get("output_type") == 4:
                return observation
            captured_release_requests.append(params)
            if len(captured_release_requests) == 1:
                return {"observations": [{
                    "date": "2015-08-01", "value": "4.1",
                    "realtime_start": "2015-09-04",
                }]}
            return {"observations": [{
                "date": "2015-08-01", "value": "4.2",
                "realtime_start": "2020-01-10",
            }]}

        with mock.patch.object(fred, "_request", side_effect=_response):
            out = fred.get_macro_data("unemployment", "2026-07-14", 4000)

        self.assertEqual(len(captured_release_requests), 3)
        for params in captured_release_requests:
            start = fred.datetime.strptime(params["realtime_start"], "%Y-%m-%d")
            end = fred.datetime.strptime(params["realtime_end"], "%Y-%m-%d")
            self.assertLess((end - start).days, fred.MAX_VINTAGE_WINDOW_DAYS)
        self.assertEqual(out.observations[0].published_at, "2015-09-04")
        self.assertEqual(out.observations[0].revision_status, "revised")

    def test_point_in_time_uses_cutoff_vintage_and_marks_revision(self):
        from tradingagents.runtime.audit_context import (
            bind_analysis_mode, bind_information_cutoff, bind_run_id,
            reset_analysis_mode, reset_information_cutoff, reset_run_id,
        )

        current = {"observations": [
            {"date": "2025-06-01", "value": "4.4"},
        ]}
        initial = {"observations": [
            {
                "date": "2025-06-01", "value": "4.1",
                "realtime_start": "2025-07-05",
            },
        ]}
        captured = []

        def response(path, params):
            captured.append((path, params))
            if path == "series":
                return _META
            return initial if params.get("output_type") == 4 else current

        run_token = bind_run_id("fred-vintage")
        mode_token = bind_analysis_mode("point_in_time")
        cutoff_token = bind_information_cutoff("2025-07-10T16:00:00-04:00")
        try:
            with mock.patch.object(fred, "_request", side_effect=response):
                out = fred.get_macro_data("unemployment", "2025-07-10", 60)
        finally:
            reset_information_cutoff(cutoff_token)
            reset_analysis_mode(mode_token)
            reset_run_id(run_token)

        vintage_request = next(
            params for path, params in captured
            if path == "series/observations" and "vintage_dates" in params
        )
        self.assertEqual(vintage_request["vintage_dates"], "2025-07-09")
        self.assertEqual(out.vintage_date, "2025-07-09")
        self.assertEqual(out.revision_policy, "fred_vintage_before_cutoff_date")
        self.assertEqual(out.observations[0].published_at, "2025-07-05")
        self.assertEqual(out.observations[0].revision_status, "revised")
        from tradingagents.dataflows.evidence_models import validate_macro_series
        validated = validate_macro_series(
            out,
            expected_vendor="fred",
            information_cutoff="2025-07-10T16:00:00-04:00",
        )
        self.assertEqual(validated.observations[0].value, 4.4)
        from dataclasses import replace
        future_release = replace(
            out,
            observations=(replace(
                out.observations[0], published_at="2025-07-11"
            ),),
        )
        with self.assertRaisesRegex(ValueError, "no macro observations"):
            validate_macro_series(
                future_release,
                expected_vendor="fred",
                information_cutoff="2025-07-10T16:00:00-04:00",
            )
        self.assertNotEqual(
            fred.macro_source_id(
                "UNRATE", "2025-06-01", vintage_date="2025-07-10"
            ),
            fred.macro_source_id(
                "UNRATE", "2025-06-01", vintage_date="2025-07-11"
            ),
        )


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
                vendor="fred", vintage_date="2026-06-01",
                revision_policy="fred_explicit_vintage",
                requested_indicator="cpi",
                observations=(fred.MacroObservation(
                    source_id=fred.macro_source_id(
                        "CPI", "2026-05-01", vintage_date="2026-06-01"
                    ),
                    series_id="CPI", title="CPI",
                    units="Index", frequency="Monthly", observed_at="2026-05-01",
                    value=100.0, vendor="fred",
                    published_at="2026-05-15", vintage_date="2026-06-01",
                    revision_status="initial",
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
