#!/usr/bin/env python3
"""
Web Search Tool Demo
====================
验证通过本地 OpenClaw 网关调用模型的 web_search / function_calling 能力。

测试项：
  [1] 直接问答（无工具）          - 基础连通性验证
  [2] 模拟 web_search 工具调用   - 通过 function calling 模拟搜索工具
  [3] 真实 web_search（若支持）  - 检测网关是否透传 web_search tool

使用方法：
  cd /path/to/TradingAgents
  python test_web_search.py
"""

import os
import json
import traceback
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.environ.get("OPENAI_API_BASE", "http://127.0.0.1:4000/v1")
API_KEY  = os.environ.get("OPENAI_API_KEY", "")
MODEL    = os.environ.get("CUSTOM_QUICK_MODEL", "kimi-code")
TIMEOUT  = 60

print("=" * 62)
print("  Web Search Tool - 功能验证")
print("=" * 62)
print(f"  BASE_URL : {BASE_URL}")
print(f"  API_KEY  : {API_KEY[:8]}{'*' * max(0, len(API_KEY) - 8)}")
print(f"  MODEL    : {MODEL}")
print("=" * 62)

passed = 0
failed = 0

def ok(msg=""):
    global passed
    passed += 1
    print(f"  ✅ {msg}")

def fail(msg, e=None):
    global failed
    failed += 1
    if e:
        print(f"  ❌ {msg}: {e}")
    else:
        print(f"  ❌ {msg}")

from openai import OpenAI
client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

# ─────────────────────────────────────────────────────────
# Test 1: 基础问答 - 确认网关连通
# ─────────────────────────────────────────────────────────
print("\n[Test 1] 基础问答 - 确认网关连通")
try:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "今天 NVDA 股价大概多少？（尽量用你已知信息回答）"}],
        max_tokens=100,
        timeout=TIMEOUT,
    )
    content = resp.choices[0].message.content
    ok(f"回复: {content[:100]}")
except Exception as e:
    fail("基础问答失败", e)
    traceback.print_exc()

# ─────────────────────────────────────────────────────────
# Test 2: 模拟 web_search 工具（function calling）
# ─────────────────────────────────────────────────────────
print("\n[Test 2] 模拟 web_search 工具 - function calling")

web_search_tool = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "搜索互联网获取最新信息，包括股票价格、新闻、财经资讯等实时数据。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，例如：'NVDA stock price today'"
                }
            },
            "required": ["query"]
        }
    }
}

try:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "请搜索 NVDA 今天的最新股价和新闻。"}],
        tools=[web_search_tool],
        tool_choice="auto",
        max_tokens=200,
        timeout=TIMEOUT,
    )

    msg = resp.choices[0].message
    if msg.tool_calls:
        call = msg.tool_calls[0]
        args = json.loads(call.function.arguments)
        ok(f"触发工具调用: {call.function.name}(query='{args.get('query', '')}')")
        print(f"  ℹ️  tool_call_id = {call.id}")

        # 模拟搜索结果，继续对话
        # ⚠️ 必须把 assistant 消息手动序列化为 dict，
        #   直接传 SDK 对象会导致 litellm 在 id 格式转换时出错（web_search:1 对不上）
        print("  🔍 模拟搜索结果，请求模型生成最终回答...")
        assistant_dict = {
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ],
        }
        messages = [
            {"role": "user", "content": "请搜索 NVDA 今天的最新股价和新闻。"},
            assistant_dict,
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps({
                    "results": [
                        {"title": "NVDA Stock Today", "snippet": "NVIDIA (NVDA) is trading at approximately $875 today. Up 2.3% from yesterday.", "url": "https://finance.example.com/nvda"},
                        {"title": "NVIDIA News", "snippet": "NVIDIA announces new AI chip partnership with major cloud providers.", "url": "https://news.example.com/nvidia"}
                    ]
                }, ensure_ascii=False)
            }
        ]

        final_resp = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=[web_search_tool],   # ⚠️ Anthropic 路由：每轮都必须带 tools=
            max_tokens=200,
            timeout=TIMEOUT,
        )
        final_content = final_resp.choices[0].message.content
        ok(f"最终回答: {final_content[:150]}")
    else:
        content = msg.content or ""
        print(f"  ⚠️  模型未触发工具调用，直接回答: {content[:100]}")
        print("     → 该模型可能不支持 function calling，或关键词未触发工具")
        failed += 1
except Exception as e:
    fail("function calling 测试失败", e)
    traceback.print_exc()

# ─────────────────────────────────────────────────────────
# Test 3: 检测是否支持原生 web_search（如 Kimi / 部分模型内置）
# ─────────────────────────────────────────────────────────
print("\n[Test 3] 检测内置 web_search（部分模型如 Kimi 原生支持）")

builtin_search_tool = {
    "type": "builtin_function",
    "function": {"name": "$web_search"}
}

try:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "搜索今天 NVIDIA 股价，用中文简要汇报。"}],
        tools=[builtin_search_tool],
        max_tokens=300,
        timeout=TIMEOUT,
    )

    msg = resp.choices[0].message
    finish = resp.choices[0].finish_reason

    if msg.tool_calls:
        call = msg.tool_calls[0]
        ok(f"调用了内置工具: {call.function.name}")
    elif msg.content:
        ok(f"内置搜索回答: {msg.content[:150]}")
        print(f"  (finish_reason={finish})")
    else:
        print(f"  ⚠️  无内容返回，finish_reason={finish}")
        failed += 1
except Exception as e:
    print(f"  ⏭️  跳过：模型不支持 builtin_function ({type(e).__name__}: {str(e)[:80]})")

# ─────────────────────────────────────────────────────────
# 汇总
# ─────────────────────────────────────────────────────────
total = passed + failed
print(f"\n{'=' * 62}")
print(f"  结果汇总: {passed}/{total} 通过  {'✅ 全部正常' if failed == 0 else '⚠️  存在问题，详见上方输出'}")
print(f"{'=' * 62}")
