"""Tests that empty vendor results never become fabricated data.

Covers two systematic fixes:
  - load_ohlcv must not cache an empty download (cache poisoning), and must
    raise NoMarketDataError instead of returning an empty frame.
  - route_to_vendor must raise NoMarketDataError after all configured OHLCV
    vendors are exhausted, so invalid data cannot enter the analysis graph.
"""

import os
import unittest
from unittest import mock

import pandas as pd
import pytest

from tradingagents.dataflows import interface, stockstats_utils
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.symbol_utils import NoMarketDataError


@pytest.mark.unit
class TestLoadOhlcvNoPoison(unittest.TestCase):
    def setUp(self):
        self._tmp = os.path.join(os.path.dirname(__file__), "_tmp_cache")
        os.makedirs(self._tmp, exist_ok=True)
        set_config({"data_cache_dir": self._tmp})

    def tearDown(self):
        for f in os.listdir(self._tmp):
            os.remove(os.path.join(self._tmp, f))
        os.rmdir(self._tmp)

    def test_empty_download_raises_and_does_not_cache(self):
        with mock.patch("tradingagents.dataflows.symbol_utils.is_westock_available", return_value=True), \
                mock.patch("tradingagents.dataflows.symbol_utils.run_westock", return_value="[]") as run, \
                mock.patch("tradingagents.dataflows.interface.route_to_vendor", side_effect=NoMarketDataError("FAKE")), \
                self.assertRaises(NoMarketDataError):
            stockstats_utils.load_ohlcv("FAKE", "2026-01-01")
        # Nothing should have been written to the cache.
        self.assertEqual(os.listdir(self._tmp), [])

        # A second call must re-attempt the fetch (no poisoned cache served).
        with mock.patch("tradingagents.dataflows.symbol_utils.is_westock_available", return_value=True), \
                mock.patch("tradingagents.dataflows.symbol_utils.run_westock", return_value="[]") as run2, \
                mock.patch("tradingagents.dataflows.interface.route_to_vendor", side_effect=NoMarketDataError("FAKE")):
            with self.assertRaises(NoMarketDataError):
                stockstats_utils.load_ohlcv("FAKE", "2026-01-01")
            self.assertTrue(run.called)
            self.assertTrue(run2.called)


@pytest.mark.unit
class TestRouteToVendorSentinel(unittest.TestCase):
    def setUp(self):
        # Pin data_vendors to the two vendors this test mocks; the global
        # DEFAULT_CONFIG may point at other (e.g. longbridge) vendors whose
        # absence would short-circuit the routing test before the mocked
        # vendors ever run.
        set_config({
            "data_vendors": {
                "core_stock_apis": "westock, alpha_vantage",
                "technical_indicators": "westock, alpha_vantage",
                "fundamental_data": "westock, alpha_vantage",
                "news_data": "alpha_vantage",
            }
        })

    def test_no_data_from_all_vendors_raises(self):
        def raises_no_data(symbol, *a, **k):
            raise NoMarketDataError(symbol, "GC=F", "no rows")

        patched = {"westock": raises_no_data, "alpha_vantage": raises_no_data}
        with mock.patch.dict(
            interface.VENDOR_METHODS, {"get_stock_data": patched}, clear=False
        ):
            with self.assertRaises(NoMarketDataError) as ctx:
                interface.route_to_vendor(
                    "get_stock_data", "XAUUSD+", "2026-01-01", "2026-01-10"
                )
        self.assertEqual(ctx.exception.symbol, "XAUUSD+")
        self.assertEqual(ctx.exception.canonical, "GC=F")

    def test_unconfigured_fallback_does_not_mask_no_data(self):
        # When the primary vendor reports no data and the fallback is simply
        # unavailable (e.g. missing API key -> raises), the no-data sentinel
        # must win rather than the fallback's incidental error crashing out.
        def raises_no_data(symbol, *a, **k):
            raise NoMarketDataError(symbol, symbol, "no rows")

        def raises_unavailable(symbol, *a, **k):
            raise ValueError("ALPHA_VANTAGE_API_KEY environment variable is not set.")

        patched = {"westock": raises_no_data, "alpha_vantage": raises_unavailable}
        with mock.patch.dict(
            interface.VENDOR_METHODS, {"get_stock_data": patched}, clear=False
        ):
            with self.assertRaises(NoMarketDataError):
                interface.route_to_vendor(
                    "get_stock_data", "FAKE", "2026-01-01", "2026-01-10"
                )


if __name__ == "__main__":
    unittest.main()
