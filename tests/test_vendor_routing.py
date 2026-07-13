"""Vendor router must respect the configured chain and never silently hide a
broken primary.

Regressions for #988 (explicit single-vendor config still fell back to others),
#289 (fallback ran for unchosen vendors), and #989 (serious primary failures
were swallowed without a trace).
"""
import copy
import unittest
from unittest import mock

import pytest

import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config
from tradingagents.dataflows import interface
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.symbol_utils import NoMarketDataError


VALID_OHLCV = "Date,Open,High,Low,Close,Volume\n2026-01-09,100,105,99,103,1000\n"


def _reset_config():
    # Hard reset: set_config() merges, so empty DEFAULT dicts (e.g. tool_vendors)
    # don't clear keys leaked by other tests. Replace the global outright.
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


def _no_data(symbol, *a, **k):
    raise NoMarketDataError(symbol, symbol, "no rows")


def _returns(value):
    def impl(symbol, *a, **k):
        return value
    return impl


def _raises(exc):
    def impl(symbol, *a, **k):
        raise exc
    return impl


@pytest.mark.unit
class VendorRoutingTests(unittest.TestCase):
    def setUp(self):
        _reset_config()

    def tearDown(self):
        _reset_config()

    def _route(self, vendors_for_get_stock_data):
        return mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_stock_data": vendors_for_get_stock_data},
            clear=False,
        )

    def test_explicit_single_vendor_does_not_fall_back(self):
        # #988: with westock pinned, a healthy alpha_vantage must NOT be used.
        set_config({"data_vendors": {"core_stock_apis": "westock"}})
        av = mock.Mock(side_effect=_returns(VALID_OHLCV))
        with self._route({"westock": _no_data, "alpha_vantage": av}):
            with self.assertRaises(NoMarketDataError):
                interface.route_to_vendor("get_stock_data", "FAKE", "2026-01-01", "2026-01-10")
        av.assert_not_called()  # the unchosen vendor was never tried

    def test_explicit_multi_vendor_falls_back_within_chain(self):
        # Listing both vendors opts in to ordered fallback.
        set_config({"data_vendors": {"core_stock_apis": "westock,alpha_vantage"}})
        with self._route({"westock": _no_data, "alpha_vantage": _returns(VALID_OHLCV)}):
            result = interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertEqual(result, VALID_OHLCV)

    def test_invalid_primary_data_falls_back_to_next_vendor(self):
        set_config({"data_vendors": {"core_stock_apis": "westock,alpha_vantage"}})
        invalid = "Date,Open,High,Low,Close,Volume\n2026-01-09,100,90,99,103,1000\n"
        with self._route({"westock": _returns(invalid), "alpha_vantage": _returns(VALID_OHLCV)}):
            result = interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertEqual(result, VALID_OHLCV)

    def test_all_invalid_data_raises(self):
        set_config({"data_vendors": {"core_stock_apis": "westock,alpha_vantage"}})
        with self._route({"westock": _returns("bad"), "alpha_vantage": _returns("also bad")}):
            with self.assertRaisesRegex(NoMarketDataError, "unparseable OHLCV"):
                interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")

    def test_invalid_amount_falls_back_to_next_vendor(self):
        set_config({"data_vendors": {"core_stock_apis": "westock,alpha_vantage"}})
        invalid = (
            "Date,Open,High,Low,Close,Volume,Amount\n"
            "2026-01-09,100,105,99,103,1000,100000000\n"
        )
        with self._route({"westock": _returns(invalid), "alpha_vantage": _returns(VALID_OHLCV)}):
            result = interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertEqual(result, VALID_OHLCV)

    def test_valid_lowercase_amount_is_accepted(self):
        set_config({"data_vendors": {"core_stock_apis": "westock"}})
        valid = (
            "date,open,high,low,close,volume,amount\n"
            "2026-01-09,100,105,99,103,1000,102000\n"
        )
        with self._route({"westock": _returns(valid)}):
            result = interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertEqual(result, valid)

    def test_invalid_turnover_alias_raises(self):
        set_config({"data_vendors": {"core_stock_apis": "longbridge_mcp"}})
        invalid = (
            "Date,Open,High,Low,Close,Volume,Turnover\n"
            "2026-01-09,100,105,99,103,1000,-1\n"
        )
        with self._route({"longbridge_mcp": _returns(invalid)}):
            with self.assertRaisesRegex(NoMarketDataError, "amount must not be negative"):
                interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")

    def test_primary_error_is_logged_not_masked(self):
        # #989: primary errors + fallback no-data -> NO_DATA, but the failure
        # must be visible in logs (broken primary not hidden).
        set_config({"data_vendors": {"core_stock_apis": "westock,alpha_vantage"}})
        with self._route({"westock": _raises(ValueError("boom")), "alpha_vantage": _no_data}), \
                self.assertLogs("tradingagents.dataflows.interface", level="WARNING") as cm, \
                self.assertRaises(NoMarketDataError):
            interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        joined = "\n".join(cm.output)
        self.assertIn("boom", joined)            # the real error surfaced in logs
        self.assertIn("westock", joined)

    def test_unknown_configured_vendor_raises(self):
        set_config({"data_vendors": {"core_stock_apis": "bogus_vendor"}})
        with self.assertRaises(ValueError) as ctx:
            interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertIn("bogus_vendor", str(ctx.exception))

    def test_default_sentinel_uses_all_vendors(self):
        # No explicit choice ("default") keeps the resilient full-chain behavior.
        set_config({"data_vendors": {"core_stock_apis": "default"}})
        with self._route({"westock": _no_data, "alpha_vantage": _returns(VALID_OHLCV)}):
            result = interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertEqual(result, VALID_OHLCV)

    def _route_method(self, method, vendors):
        return mock.patch.dict(interface.VENDOR_METHODS, {method: vendors}, clear=False)

    def test_optional_category_degrades_instead_of_raising(self):
        # An optional prediction-market enrichment that raises must NOT abort
        # the run — the router returns a sentinel so the analysis proceeds.
        set_config({"data_vendors": {"prediction_markets": "polymarket"}})
        with self._route_method(
            "get_prediction_markets",
            {"polymarket": _raises(ValueError("prediction API unavailable"))},
        ):
            result = interface.route_to_vendor("get_prediction_markets", "Fed cut", 5)
        self.assertIn("DATA_UNAVAILABLE", result)
        self.assertIn("prediction_markets", result)

    def test_core_category_still_raises_on_error(self):
        # A core category (single configured vendor) propagates the error so a
        # broken primary is loud, not silently degraded.
        set_config({"data_vendors": {"core_stock_apis": "westock"}})
        with self._route({"westock": _raises(ValueError("boom"))}), \
                self.assertRaises(ValueError):
            interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")


if __name__ == "__main__":
    unittest.main()
