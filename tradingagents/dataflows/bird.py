"""Read-only X/Twitter vendor backed by the bird CLI."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import shutil
import subprocess

from .errors import NoMarketDataError, VendorNotConfiguredError, VendorRateLimitError
from .social_data import SocialFeed, SocialPost


def get_social_posts(symbol: str, start_date: str, end_date: str) -> SocialFeed:
    if shutil.which("bird") is None:
        raise VendorNotConfiguredError("bird CLI is not installed")
    until = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    query = f"${symbol.lstrip('$')} since:{start_date} until:{until} -is:retweet"
    try:
        completed = subprocess.run(
            ["bird", "search", query, "-n", "30", "--json", "--plain", "--no-color"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise VendorRateLimitError("bird search timed out") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "bird search failed").strip()
        lowered = detail.lower()
        if "429" in lowered or "rate limit" in lowered:
            raise VendorRateLimitError(detail)
        if "auth" in lowered or "cookie" in lowered or "credential" in lowered:
            raise VendorNotConfiguredError(detail)
        raise RuntimeError(detail)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("bird returned invalid JSON") from exc
    if not isinstance(payload, list) or not payload:
        raise NoMarketDataError(symbol, detail="bird returned no matching posts")
    posts = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            created = datetime.strptime(item["createdAt"], "%a %b %d %H:%M:%S %z %Y")
        except (KeyError, TypeError, ValueError):
            continue
        author = item.get("author") or {}
        posts.append(SocialPost(
            post_id=str(item.get("id") or ""),
            text=str(item.get("text") or ""),
            created_at=created,
            author_id=str(item.get("authorId") or ""),
            username=str(author.get("username") or "unknown"),
            reply_count=int(item.get("replyCount") or 0),
            repost_count=int(item.get("retweetCount") or 0),
            like_count=int(item.get("likeCount") or 0),
        ))
    if not posts:
        raise NoMarketDataError(symbol, detail="bird posts lacked required fields")
    return SocialFeed(source="bird", symbol=symbol, posts=tuple(posts))
