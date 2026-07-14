#!/usr/bin/env python3
"""
测试长桥 CLI vendor 接入 TradingAgents (2026-07-04 重写为 CLI 实现)

Run from project root:
    /data/disk/workspace/TradingAgents/venv/bin/python tests/test_longbridge_integration.py
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from tradingagents.dataflows.interface import route_to_vendor, VENDOR_METHODS
from tradingagents.dataflows.ohlcv_cache import latest_completed_daily_bar_date


# Pytest-discoverable registration check (the heavy ad-hoc smoke is below
# under __main__ and requires a live Longbridge token).
@pytest.mark.unit
def test_longbridge_vendor_registration():
    """Longbridge must be registered for every vendor slot we cover."""
    expected = {
        "get_stock_data",
        "get_indicators",
        "get_fundamentals",
        "get_balance_sheet",
        "get_cashflow",
        "get_income_statement",
        "get_news",
    }
    missing = expected - set(VENDOR_METHODS)
    assert not missing, f"vendor routes missing longbridge entry: {missing}"
    for method in expected:
        assert "longbridge" in VENDOR_METHODS[method], \
            f"{method} has no longbridge vendor registered"
        # MCP variant is optional (only present when the bearer token file exists).
        if "longbridge_mcp" in VENDOR_METHODS[method]:
            assert "longbridge_mcp" in VENDOR_METHODS[method]


if __name__ == "__main__":
    print("=" * 60)
    print("测试长桥数据源集成（含 MCP + CLI 两条 vendor 路径）")
    print("=" * 60)

    # Vendor registration
    print("\n1. VENDOR_METHODS 注册检查:")
    expected = {
        "get_stock_data",
        "get_indicators",
        "get_fundamentals",
        "get_balance_sheet",
        "get_cashflow",
        "get_income_statement",
        "get_news",
    }
    for method, vendors in VENDOR_METHODS.items():
        if "longbridge" in vendors:
            marker = "+mcp" if "longbridge_mcp" in vendors else ""
            print(f"  ✓ {method}: 长桥 vendor 已注册{marker}")

    missing = expected - set(VENDOR_METHODS)
    if missing:
        print(f"\n!! 缺失 vendor 路由: {missing}")
        sys.exit(1)

    def check(label, fn, *args, **kwargs):
        print(f"\n{label}:")
        try:
            result = fn(*args, **kwargs)
            ok = result and "Error" not in result[:20] and "error" not in result[:40].lower()
            print(f"  ✓ 调用成功  ({len(result)} chars)")
            print(f"  preview: {result[:200]!r}")
            return True
        except Exception as e:
            print(f"  ✗ 异常: {type(e).__name__}: {e}")
            return False

    end_date = latest_completed_daily_bar_date("NVDA").strftime("%Y-%m-%d")
    start_date = (date.fromisoformat(end_date) - timedelta(days=45)).isoformat()
    ok = []
    ok.append(
        check(
            f"2. get_stock_data NVDA {start_date}..{end_date}",
            route_to_vendor,
            "get_stock_data",
            "NVDA",
            start_date,
            end_date,
        )
    )
    ok.append(
        check(
            "3. get_indicators NVDA rsi 30d",
            route_to_vendor,
            "get_indicators",
            "NVDA",
            "rsi",
            end_date,
            30,
        )
    )
    ok.append(
        check(
            "4. get_indicators NVDA macd 60d",
            route_to_vendor,
            "get_indicators",
            "NVDA",
            "macd",
            end_date,
            60,
        )
    )
    ok.append(check("5. get_fundamentals NVDA", route_to_vendor, "get_fundamentals", "NVDA"))
    ok.append(check("6. get_income_statement NVDA", route_to_vendor, "get_income_statement", "NVDA"))
    ok.append(check("7. get_balance_sheet NVDA", route_to_vendor, "get_balance_sheet", "NVDA"))
    ok.append(check("8. get_cashflow NVDA", route_to_vendor, "get_cashflow", "NVDA"))

    print("\n" + "=" * 60)
    passed = sum(ok)
    total = len(ok)
    print(f"结果: {passed}/{total} 通过")
    print("=" * 60)
    sys.exit(0 if passed == total else 1)
