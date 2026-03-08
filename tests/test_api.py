#!/usr/bin/env python3
"""
TradingAgents 接口完整验证脚本
读取 .env 配置，依次测试：
  [1] 连通性          - GET /models（可选）
  [2] 原生非流式      - openai SDK invoke
  [3] 原生流式        - openai SDK stream
  [4] LangChain 非流式 - ChatOpenAI.invoke()
  [5] LangChain 流式  - ChatOpenAI.stream()
  [6] 工具绑定        - bind_tools()（Agent 核心）
"""

import os
import sys
import traceback
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.environ.get("OPENAI_API_BASE", "http://127.0.0.1:4000/v1")
API_KEY  = os.environ.get("OPENAI_API_KEY", "")
MODEL    = os.environ.get("CUSTOM_QUICK_MODEL", "kimi-code")
TIMEOUT  = 30

print("=" * 62)
print("  TradingAgents - 接口完整验证")
print("=" * 62)
print(f"  BASE_URL : {BASE_URL}")
print(f"  API_KEY  : {API_KEY[:8]}{'*' * max(0, len(API_KEY) - 8)}")
print(f"  MODEL    : {MODEL}")
print(f"  TIMEOUT  : {TIMEOUT}s")
print("=" * 62)

passed = 0
failed = 0

def ok(msg=""):
    global passed
    passed += 1
    print(f"  ✅ {msg}")

def fail(msg, e):
    global failed
    failed += 1
    print(f"  ❌ {msg}: {e}")

def skip(msg):
    print(f"  ⏭️  跳过：{msg}")

# ─────────────────────────────────────────────────────────
# Test 1: 连通性 GET /models（可选）
# ─────────────────────────────────────────────────────────
print("\n[Test 1] 连通性检查 - GET /models（可选）")
try:
    import httpx
    headers = {"Authorization": f"Bearer {API_KEY}"}
    resp = httpx.get(f"{BASE_URL}/models", headers=headers, timeout=10)
    if resp.status_code == 200:
        models = [m["id"] for m in resp.json().get("data", [])]
        ok(f"共 {len(models)} 个模型")
        for m in models[:8]:
            print(f"     - {m}{' ← 当前使用' if m == MODEL else ''}")
        if MODEL not in models:
            print(f"  ⚠️  '{MODEL}' 不在模型列表中")
    elif resp.status_code in (404, 405):
        skip(f"接口返回 {resp.status_code}，网关不提供 /models 属于正常")
    else:
        print(f"  ⚠️  状态码 {resp.status_code}: {resp.text[:150]}")
except httpx.ConnectError as e:
    fail("无法连接", e)
    print("  → 请确认本地网关服务已启动，后续测试将跳过")
    sys.exit(1)
except Exception as e:
    skip(str(e))

# ─────────────────────────────────────────────────────────
# Test 2 & 3: 原生 OpenAI SDK
# ─────────────────────────────────────────────────────────
from openai import OpenAI
raw_client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

print(f"\n[Test 2] 原生 SDK - 非流式 (model={MODEL})")
try:
    resp = raw_client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "用一句话介绍你自己。"}],
        max_tokens=80,
        timeout=TIMEOUT,
    )
    content = resp.choices[0].message.content
    ok(f"回复: {content[:80]}")
except Exception as e:
    fail("非流式调用失败", e)

print(f"\n[Test 3] 原生 SDK - 流式 (stream=True)")
try:
    print("  💬 ", end="", flush=True)
    stream = raw_client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "用一句话说今天天气很好。"}],
        max_tokens=60,
        stream=True,
        timeout=TIMEOUT,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            print(delta.content, end="", flush=True)
    print()
    ok("流式传输正常")
except Exception as e:
    print()
    fail("流式调用失败", e)

# ─────────────────────────────────────────────────────────
# Test 4 & 5: LangChain ChatOpenAI（TradingAgents 实际用法）
# ─────────────────────────────────────────────────────────
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

print(f"\n[Test 4] LangChain - 非流式 invoke()")
try:
    llm = ChatOpenAI(model=MODEL, base_url=BASE_URL, api_key=API_KEY, timeout=TIMEOUT)
    resp = llm.invoke([HumanMessage(content="用一句话介绍你自己。")])
    ok(f"回复: {str(resp.content)[:80]}")
except Exception as e:
    fail("LangChain invoke 失败", e)
    traceback.print_exc()

print(f"\n[Test 5] LangChain - 流式 stream()")
try:
    print("  💬 ", end="", flush=True)
    for chunk in llm.stream([HumanMessage(content="用一句话说今天天气很好。")]):
        print(chunk.content, end="", flush=True)
    print()
    ok("流式传输正常")
except Exception as e:
    print()
    fail("LangChain stream 失败", e)
    traceback.print_exc()

# ─────────────────────────────────────────────────────────
# Test 6: 工具绑定（Agent 核心用法，最关键）
# ─────────────────────────────────────────────────────────
print(f"\n[Test 6] LangChain - 工具绑定 bind_tools()【Agent 核心】")
try:
    from langchain_core.tools import tool

    @tool
    def get_stock_price(ticker: str) -> str:
        """获取股票实时价格"""
        return f"{ticker} 当前价格: $150.00"

    llm_with_tools = llm.bind_tools([get_stock_price])
    resp = llm_with_tools.invoke([HumanMessage(content="帮我查一下 AAPL 的股价")])

    if resp.tool_calls:
        ok(f"✅ 正确触发工具调用: {resp.tool_calls[0]['name']}({resp.tool_calls[0]['args']})")
    else:
        content_preview = str(resp.content)[:100]
        print(f"  ⚠️  模型未触发工具调用，直接回答: {content_preview}")
        print("     → TradingAgents 依赖工具调用推进流程，此模型可能导致 Agents 卡死")
        failed += 1
except Exception as e:
    fail("工具绑定测试失败", e)
    traceback.print_exc()

# ─────────────────────────────────────────────────────────
# 汇总
# ─────────────────────────────────────────────────────────
total = passed + failed
print(f"\n{'=' * 62}")
print(f"  结果汇总: {passed}/{total} 通过  {'✅ 全部正常' if failed == 0 else '⚠️  存在问题，详见上方输出'}")
print(f"{'=' * 62}")
