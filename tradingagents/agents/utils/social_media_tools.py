"""
Social Media Tools - Twitter/X 数据获取
通过 bird CLI 工具搜索 Twitter/X 上的股票讨论和舆情数据。

依赖：
  - bird CLI 已安装（x-news 项目中使用的同一工具）
  - .env 中配置 BIRD_AUTH_TOKEN 和 BIRD_CT0
"""

import os
import json
import subprocess
from typing import Annotated
from langchain_core.tools import tool


def _run_bird_search(query: str, limit: int = 30) -> list[dict]:
    """调用 bird CLI 执行 Twitter/X 搜索，返回推文列表。"""
    auth_token = os.environ.get("BIRD_AUTH_TOKEN", "")
    ct0 = os.environ.get("BIRD_CT0", "")

    if not auth_token or not ct0:
        raise RuntimeError(
            "BIRD_AUTH_TOKEN 或 BIRD_CT0 未配置，请在 .env 中添加。\n"
            "参考 x-news/.env 中的配置。"
        )

    cmd = [
        "bird", "search", query,
        "-n", str(limit),
        "--json",
        "--auth-token", auth_token,
        "--ct0", ct0,
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        raise RuntimeError(f"bird 命令失败: {result.stderr[:200]}")

    raw = json.loads(result.stdout)
    return raw if isinstance(raw, list) else raw.get("tweets", [])


def _format_tweets(tweets: list[dict], max_tweets: int = 20) -> str:
    """将推文列表格式化为可读字符串供 LLM 分析。"""
    if not tweets:
        return "未找到相关推文。"

    lines = [f"共找到 {len(tweets)} 条推文，以下为前 {min(len(tweets), max_tweets)} 条：\n"]

    for i, t in enumerate(tweets[:max_tweets], 1):
        author = t.get("author", {})
        username = author.get("userName") or author.get("username", "unknown")
        name = author.get("name", "")
        text = t.get("text", "").replace("\n", " ")[:280]
        likes = t.get("likeCount", 0)
        retweets = t.get("retweetCount", 0)
        replies = t.get("replyCount", 0)
        created_at = t.get("createdAt", "")[:10]
        url = t.get("url", f"https://x.com/i/status/{t.get('id', '')}")

        lines.append(
            f"[{i}] @{username}（{name}）{created_at}\n"
            f"    {text}\n"
            f"    ❤️ {likes}  🔁 {retweets}  💬 {replies}  {url}\n"
        )

    return "\n".join(lines)


@tool
def get_twitter_stock_sentiment(
    ticker: Annotated[str, "股票代码，例如 NVDA、AAPL、TSLA"],
    company_name: Annotated[str, "公司名称，例如 NVIDIA、Apple，用于补充搜索"],
    limit: Annotated[int, "最多获取的推文数量，默认 30"] = 30,
) -> str:
    """
    从 Twitter/X 搜索关于指定股票的最新讨论和市场情绪。

    搜索投资者、分析师、KOL 对该股票的看法，包括：
    - 股价预测和分析
    - 公司新闻反应
    - 多空观点
    - 散户情绪

    Args:
        ticker: 股票代码（如 NVDA）
        company_name: 公司名称（如 NVIDIA）
        limit: 获取推文数量上限

    Returns:
        格式化的推文列表，包含作者、内容、互动数据
    """
    try:
        # 构建更专业的搜索词：需要极高互动量(100赞/评/转)以筛选出最高质量的市场资讯
        query = f'({ticker} OR "{company_name}") (stock OR market OR 财报 OR 股价) (min_faves:100 OR min_retweets:100 OR min_replies:100) -is:retweet'
        tweets = _run_bird_search(query, limit=limit)
        # 按互动量排序
        tweets.sort(key=lambda t: t.get("likeCount", 0) + t.get("retweetCount", 0), reverse=True)
        return _format_tweets(tweets)
    except Exception as e:
        return f"Twitter 数据获取失败: {e}"


@tool
def get_twitter_trending_finance(
    limit: Annotated[int, "最多获取的推文数量，默认 30"] = 30,
) -> str:
    """
    从 Twitter/X 获取当前金融市场热议话题和趋势。

    搜索财经 KOL、分析师对宏观市场的最新观点，包括：
    - 美联储政策讨论
    - 宏观经济趋势
    - 热门板块动向
    - 市场情绪指标

    Args:
        limit: 获取推文数量上限

    Returns:
        格式化的市场热议推文列表
    """
    try:
        query = "(stock market OR 股市 OR Fed OR 美联储 OR macro OR 宏观) (trading OR investing OR 投资) -is:retweet"
        tweets = _run_bird_search(query, limit=limit)
        tweets.sort(key=lambda t: t.get("likeCount", 0) + t.get("retweetCount", 0), reverse=True)
        return _format_tweets(tweets)
    except Exception as e:
        return f"Twitter 趋势数据获取失败: {e}"
