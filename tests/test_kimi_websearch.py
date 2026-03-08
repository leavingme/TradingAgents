#!/usr/bin/env python3
"""
Kimi Coding API - Anthropic 格式 web_search 验证
==================================================
kimi-code 的后端是 Anthropic 兼容接口（api.kimi.com/coding/），
使用 anthropic SDK + 自定义 base_url 直连，绕过 LiteLLM 代理。

来源（litellm config.yaml）：
  model: anthropic/kimi-coding/k2p5
  api_key: sk-kimi-0Xqj...
  api_base: https://api.kimi.com/coding/

使用方法：
  python test_kimi_websearch.py
"""

import os
import json
import traceback

# 直接从 litellm config.yaml 里读取
KIMI_API_KEY  = "sk-kimi-0XqjR1zwziRYN0I7XUEOxvzbbkxsE1pNy2mNDwBwRAeMBJwhBqM57YMMWLQjfBo8"
KIMI_BASE_URL = "https://api.kimi.com/coding/"
MODEL         = "kimi-coding/k2p5"
TIMEOUT       = 60

print("=" * 62)
print("  Kimi Coding API - Anthropic 格式直连验证")
print("=" * 62)
print(f"  BASE_URL : {KIMI_BASE_URL}")
print(f"  API_KEY  : {KIMI_API_KEY[:16]}...")
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

# 直连 Kimi Anthropic 兼容接口
client = anthropic.Anthropic(
    api_key=KIMI_API_KEY,
    base_url=KIMI_BASE_URL,
)

# ─────────────────────────────────────────────────────────
# Test 1: 基础连通 - 无工具问答
# ─────────────────────────────────────────────────────────
print("\n[Test 1] 基础连通 - 直连 Kimi Anthropic 接口")
try:
    resp = client.messages.create(
        model=MODEL,
        max_tokens=100,
        messages=[{"role": "user", "content": "MacBook Neo 有几个颜色，什么价格？"}],
    )
    content = resp.content[0].text if resp.content else ""
    ok(f"回复: {content[:100]}")
    print(f"  ℹ️  stop_reason={resp.stop_reason}, model={resp.model}")
except Exception as e:
    fail("连接失败", e)
    traceback.print_exc()
    exit(1)

# ─────────────────────────────────────────────────────────
# Test 2: Anthropic 格式 web_search tool
# ─────────────────────────────────────────────────────────
print("\n[Test 2] Anthropic 格式 web_search tool")
try:
    resp = client.messages.create(
        model=MODEL,
        max_tokens=500,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": "MacBook Neo 有几个颜色，什么价格？请搜索最新信息并用中文回答。"}],
    )

    print(f"  ℹ️  stop_reason={resp.stop_reason}")

    for block in resp.content:
        print(f"  ℹ️  block.type={block.type}")
        if block.type == "text":
            ok(f"文字回答: {block.text[:200]}")
        elif block.type == "tool_use":
            ok(f"触发工具: {block.name} | 参数: {block.input}")
        elif block.type == "web_search_tool_result":
            results = getattr(block, "content", [])
            ok(f"搜索结果: 共 {len(results)} 条")
            for r in results[:3]:
                print(f"     - {getattr(r, 'title', '')} | {getattr(r, 'url', '')}")

    # 如果是 tool_use，继续多轮对话拿到最终答案
    if resp.stop_reason == "tool_use":
        print("\n  ⏳ 继续对话，获取最终回答...")
        messages = [
            {"role": "user", "content": "MacBook Neo 有几个颜色，什么价格？请搜索最新信息并用中文回答。"},
            {"role": "assistant", "content": resp.content},
        ]
        final_resp = client.messages.create(
            model=MODEL,
            max_tokens=500,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=messages,
        )
        for block in final_resp.content:
            if block.type == "text":
                ok(f"最终回答:\n\n{block.text}\n")

except Exception as e:
    fail("web_search tool 调用失败", e)
    traceback.print_exc()

# ─────────────────────────────────────────────────────────
# Test 3: 尝试 Kimi 私有 builtin_function 格式（通过 Anthropic 接口）
# ─────────────────────────────────────────────────────────
print("\n[Test 3] Kimi 私有搜索格式（通过 Anthropic 接口）")
try:
    resp = client.messages.create(
        model=MODEL,
        max_tokens=300,
        tools=[{"type": "builtin_function", "function": {"name": "$web_search"}}],
        messages=[{"role": "user", "content": "MacBook Neo 有几个颜色，什么价格？"}],
    )
    for block in resp.content:
        if block.type == "text":
            ok(f"回答: {block.text[:150]}")
        else:
            ok(f"block type: {block.type}")
except Exception as e:
    print(f"  ⏭️  跳过：不支持此格式 ({type(e).__name__}: {str(e)[:100]})")

# ─────────────────────────────────────────────────────────
# 汇总
# ─────────────────────────────────────────────────────────
total = passed + failed
print(f"\n{'=' * 62}")
print(f"  结果汇总: {passed}/{total} 通过  {'✅ 全部正常' if failed == 0 else '⚠️  存在问题，详见上方输出'}")
print(f"{'=' * 62}")
