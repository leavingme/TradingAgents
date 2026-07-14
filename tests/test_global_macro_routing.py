"""Unit tests for global macro routing (CN/HK market indicators) and tool parameter robustness.

Tests symbol suffix detection, alias mapping, and automatic lookback period
expansion in dataflows/fred.py, as well as the ability of tool wrappers
to safely absorb extra arguments (hallucination parameters).
"""
import unittest
from unittest import mock
import pytest

from tradingagents.agents.utils.macro_data_tools import get_macro_indicators
from tradingagents.agents.utils.technical_indicators_tools import get_indicators
from tradingagents.agents.utils.core_stock_tools import get_stock_data
from tradingagents.dataflows import fred


@pytest.mark.unit
class GlobalMacroRoutingTests(unittest.TestCase):
    @mock.patch("tradingagents.agents.utils.macro_data_tools.route_to_vendor")
    def test_routing_by_symbol_hk(self, mock_route):
        # 1. Test HK market CPI mapping
        get_macro_indicators.func("cpi", "2026-07-11", 180, symbol="0700.HK")
        mock_route.assert_called_with("get_macro_indicators", "hk_cpi", "2026-07-11", 180)

        # 2. Test HK market GDP mapping
        get_macro_indicators.func("gdp", "2026-07-11", 180, symbol="0700.HK")
        mock_route.assert_called_with("get_macro_indicators", "hk_gdp", "2026-07-11", 180)

    @mock.patch("tradingagents.agents.utils.macro_data_tools.route_to_vendor")
    def test_routing_by_symbol_cn(self, mock_route):
        # 1. Test CN market (A-shares) CPI mapping
        get_macro_indicators.func("cpi", "2026-07-11", 180, symbol="600519.SS")
        mock_route.assert_called_with("get_macro_indicators", "cn_cpi", "2026-07-11", 180)

        # 2. Test CN market interest rate mapping
        get_macro_indicators.func("fed_funds_rate", "2026-07-11", 180, symbol="000001.SZ")
        mock_route.assert_called_with("get_macro_indicators", "cn_interest_rate", "2026-07-11", 180)

    @mock.patch("tradingagents.agents.utils.macro_data_tools.route_to_vendor")
    def test_routing_default_us(self, mock_route):
        # 1. Test US stock (default) CPI mapping
        get_macro_indicators.func("cpi", "2026-07-11", 180, symbol="NVDA")
        mock_route.assert_called_with("get_macro_indicators", "cpi", "2026-07-11", 180)

        # 2. Test no symbol provided mapping
        get_macro_indicators.func("cpi", "2026-07-11", 180, symbol=None)
        mock_route.assert_called_with("get_macro_indicators", "cpi", "2026-07-11", 180)


@pytest.mark.unit
class FredLaggingLookbackTests(unittest.TestCase):
    @mock.patch("tradingagents.dataflows.fred.get_api_key", return_value="fake_key")
    @mock.patch("tradingagents.dataflows.fred._request")
    def test_auto_lookback_expansion_for_lagging_indicators(self, mock_request, mock_key):
        # Setup mock responses for series info and observations
        def response(path, params):
            if path == "series":
                return {"seriess": [{
                    "title": "Fake China CPI", "units": "Index",
                    "frequency": "Monthly",
                }]}
            row = {"date": "2024-03-01", "value": "115.0"}
            if params.get("output_type") == 4:
                row["realtime_start"] = "2024-04-01"
            return {"observations": [row]}

        mock_request.side_effect = response

        # Retrieve a lagging indicator (cn_cpi) with a short window (180 days)
        fred.get_macro_data("cn_cpi", "2026-07-11", 180)
        
        # Verify that observation_start was pushed back by 1095 days instead of 180 days
        # 2026-07-11 - 1095 days = 2023-07-12
        obs_params = mock_request.call_args_list[1][0][1]
        self.assertEqual(obs_params["observation_start"], "2023-07-12")

        # Retrieve a regular indicator (cpi) with 180 days -> no expansion
        fred.get_macro_data("cpi", "2026-07-11", 180)
        # 2026-07-11 - 180 days = 2026-01-12
        obs_params_us = mock_request.call_args_list[4][0][1]
        self.assertEqual(obs_params_us["observation_start"], "2026-01-12")


@pytest.mark.unit
class ToolSanitizerTests(unittest.TestCase):
    """Test that tool wrapper functions safely ignore extra hallucinated keys (e.g. /invoke) from LLM output."""

    @mock.patch("tradingagents.agents.utils.technical_indicators_tools.route_to_vendor")
    def test_get_indicators_ignores_extra_args(self, mock_route):
        mock_route.return_value = "dummy_result"
        # Even if /invoke or other garbage parameters are passed, the tool function should not crash
        try:
            get_indicators.func(
                symbol="NVDA",
                indicator="macdh",
                curr_date="2026-07-11",
                look_back_days=60,
                **{"/invoke": {"invoke name=\"get_": ""}}
            )
        except TypeError as e:
            self.fail(f"get_indicators raised TypeError with extra arguments: {e}")
        
        mock_route.assert_called_with("get_indicators", "NVDA", "macdh", "2026-07-11", 60)

    @mock.patch("tradingagents.agents.utils.core_stock_tools.route_to_vendor")
    def test_get_stock_data_ignores_extra_args(self, mock_route):
        try:
            get_stock_data.func(
                symbol="NVDA",
                start_date="2025-10-01",
                end_date="2026-07-11",
                **{"/invoke": "garbage"}
            )
        except TypeError as e:
            self.fail(f"get_stock_data raised TypeError with extra arguments: {e}")
            
        mock_route.assert_called_with("get_stock_data", "NVDA", "2025-10-01", "2026-07-11")


if __name__ == "__main__":
    unittest.main()
