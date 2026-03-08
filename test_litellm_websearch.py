#!/usr/bin/env python3
"""
通过 LiteLLM 代理使用 Anthropic 格式 web_search 验证
======================================================
LiteLLM 同时暴露两套接口：
  - OpenAI 兼容：http://127.0.0.1:4000/v1/chat/completions   (openai SDK)
  - Anthropic 兼容：http://127.0.0.1:4000/v1/messages        (anthropic SDK)

重点：web_search_20250305 是 Anthropic 私有 tool 类型，
用 OpenAI 兼容接口会被 LiteLLM 拒绝/忽略；
但用 Anthropic 兼容接口，LiteLLM 可以直接透传给 Kimi 后端。

使用方法：
  python test_litellm_websearch.py
"""

import os
import json
import traceback
from dotenv import load_dotenv

load_dotenv()

# LiteLLM 代理配置（来自 .env）
LITELLM_BASE_URL = os.environ.get("OPENAI_API_BASE", "http://127.0.0.1:4000/v1").rstrip("/v1").rstrip("/")
LITELLM_API_KEY  = os.environ.get("OPENAI_API_KEY", "")
MODEL            = os.environ.get("CUSTOM_QUICK_MODEL", "kimi-code")
TIMEOUT          = 60

print("=" * 62)
print("  LiteLLM 代理 + Anthropic 格式 web_search 验证")
print("=" * 62)
print(f"  LiteLLM  : {LITELLM_BASE_URL}")
print(f"  API_KEY  : {LITELLM_API_KEY[:8]}{'*' * max(0, len(LITELLM_API_KEY) - 8)}")
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
    print(f"  ❌ {msg}: {e}" if e else f"  ❌ {msg}")

import anthropic

# ⭐ 核心：anthropic SDK 指向 LiteLLM 代理，而不是 Kimi 直连
#    LiteLLM 会接收 Anthropic 格式请求，透传给 kimi-code 后端
client = anthropic.Anthropic(
    api_key=LITELLM_API_KEY,
    base_url=LITELLM_BASE_URL,  # 指向 LiteLLM，而非 api.kimi.com
)

QUERY = "MacBook Neo 有几个颜色，什么价格？请搜索最新信息并用中文回答。"

# ─────────────────────────────────────────────────────────
# Test 1: 通过 LiteLLM Anthropic 接口 - 基础连通
# ─────────────────────────────────────────────────────────
print("\n[Test 1] 通过 LiteLLM Anthropic 接口 - 基础连通")
try:
    resp = client.messages.create(
        model=MODEL,
        max_tokens=100,
        messages=[{"role": "user", "content": "用一句话介绍自己。"}],
    )
    content = resp.content[0].text if resp.content else ""
    ok(f"回复: {content[:100]}")
    print(f"  ℹ️  model={resp.model}, stop_reason={resp.stop_reason}")
except Exception as e:
    fail("连接失败", e)
    traceback.print_exc()
    exit(1)

# ─────────────────────────────────────────────────────────
# Test 2: 通过 LiteLLM 透传 web_search_20250305
# ─────────────────────────────────────────────────────────
print(f"\n[Test 2] 通过 LiteLLM 透传 web_search_20250305")
print(f"  🔍 问题: {QUERY}")
try:
    resp = client.messages.create(
        model=MODEL,
        max_tokens=600,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": QUERY}],
    )

    print(f"  ℹ️  stop_reason={resp.stop_reason}, blocks={[b.type for b in resp.content]}")

    has_search = False
    for block in resp.content:
        if block.type == "text" and block.text.strip():
            print(f"  💬 文字: {block.text[:200]}")
        elif block.type == "server_tool_use":
            has_search = True
            ok(f"触发搜索: {block.name} | query={getattr(block, 'input', {})}")
        elif block.type == "web_search_tool_result":
            results = getattr(block, "content", [])
            ok(f"搜索结果: 共 {len(results)} 条")
            for r in results[:3]:
                print(f"     - {getattr(r, 'title', '')[:50]} | {getattr(r, 'url', '')}")
        elif block.type == "tool_use":
            ok(f"tool_use: {block.name} | {block.input}")

    # 如果有 tool_use，继续获取最终回答
    if resp.stop_reason == "tool_use":
        print("\n  ⏳ 提交结果，获取最终回答...")
        final_resp = client.messages.create(
            model=MODEL,
            max_tokens=600,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[
                {"role": "user", "content": QUERY},
                {"role": "assistant", "content": resp.content},
            ],
        )
        for block in final_resp.content:
            if block.type == "text" and block.text.strip():
                ok(f"最终回答:\n\n{block.text[:400]}\n")

    if not has_search and resp.stop_reason == "end_turn":
        # 检查是否已经在 end_turn 时内嵌了搜索结果
        search_blocks = [b for b in resp.content if b.type in ("web_search_tool_result", "server_tool_use")]
        if search_blocks:
            ok("单轮完成（搜索 + 回答 一次返回）")
        else:
            print("  ⚠️  未见搜索结果块，可能未触发 web_search")

except Exception as e:
    fail("web_search 调用失败", e)
    traceback.print_exc()

# ─────────────────────────────────────────────────────────
# 汇总
# ─────────────────────────────────────────────────────────
total = passed + failed
print(f"\n{'=' * 62}")
print(f"  结果汇总: {passed}/{total} 通过  {'✅ 全部正常' if failed == 0 else '⚠️  存在问题，详见上方输出'}")
print(f"{'=' * 62}")
