#!/usr/bin/env python3
"""
测试长桥数据源集成到 TradingAgents
"""
import sys
sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/TradingAgents')

from dotenv import load_dotenv
load_dotenv()

from tradingagents.dataflows.interface import route_to_vendor, VENDOR_METHODS

print("="*60)
print("测试长桥数据源集成")
print("="*60)

# 1. 检查长桥是否已注册
print("\n1. 检查 VENDOR_METHODS 注册:")
for method, vendors in VENDOR_METHODS.items():
    if "longbridge" in vendors:
        print(f"  ✓ {method}: 长桥已注册")

# 2. 测试获取小米股票数据
print("\n2. 测试获取小米 (1810.HK) 数据:")
try:
    result = route_to_vendor("get_stock_data", "1810.HK", "2026-02-20", "2026-02-28")
    print(f"  ✓ 数据获取成功")
    print(f"  前200字符: {result[:200]}...")
except Exception as e:
    print(f"  ✗ 错误: {e}")

# 3. 测试获取技术指标
print("\n3. 测试获取小米技术指标:")
try:
    result = route_to_vendor("get_indicators", "1810.HK", "rsi", "2026-02-28", 20)
    print(f"  ✓ 指标获取成功")
    print(f"  报告:\n{result}")
except Exception as e:
    print(f"  ✗ 错误: {e}")

# 4. 测试美股
print("\n4. 测试获取美股 NVDA 数据:")
try:
    result = route_to_vendor("get_stock_data", "NVDA", "2026-02-20", "2026-02-28")
    print(f"  ✓ 数据获取成功")
    print(f"  前200字符: {result[:200]}...")
except Exception as e:
    print(f"  ✗ 错误: {e}")

print("\n" + "="*60)
print("测试完成!")
print("="*60)
