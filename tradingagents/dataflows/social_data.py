"""Unified social-post model, deterministic validation, and LLM rendering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re


@dataclass(frozen=True)
class SocialPost:
    post_id: str
    text: str
    created_at: datetime
    author_id: str
    username: str
    reply_count: int = 0
    repost_count: int = 0
    like_count: int = 0


@dataclass(frozen=True)
class SocialFeed:
    source: str
    symbol: str
    posts: tuple[SocialPost, ...]


_SPAM = re.compile(
    r"(?:whatsapp|telegram|join (?:our|my)|link in (?:my )?bio|private (?:crypto|trading)|"
    r"trade alerts?|signals? daily|guaranteed returns?|dm me)",
    re.IGNORECASE,
)


def validate_social_feed(feed: SocialFeed, start_date: str, end_date: str) -> SocialFeed:
    if not isinstance(feed, SocialFeed):
        raise TypeError("social vendor must return SocialFeed")
    start = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc, hour=23, minute=59, second=59)
    seen: set[str] = set()
    valid = []
    for post in feed.posts:
        created = post.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if (
            not post.post_id
            or post.post_id in seen
            or not post.text.strip()
            or not post.author_id
            or not post.username
            or post.username == "unknown"
        ):
            continue
        if created < start or created > end or _SPAM.search(post.text):
            continue
        if any(value < 0 for value in (post.reply_count, post.repost_count, post.like_count)):
            continue
        seen.add(post.post_id)
        valid.append(post)
    if not valid:
        raise ValueError("no social posts passed date, uniqueness, and spam validation")
    return SocialFeed(source=feed.source, symbol=feed.symbol, posts=tuple(valid))


def render_social_feed(feed: SocialFeed) -> str:
    lines = [f"X/Twitter via {feed.source}: {len(feed.posts)} validated posts for {feed.symbol}"]
    for post in feed.posts:
        timestamp = post.created_at.astimezone(timezone.utc).isoformat()
        text = " ".join(post.text.split())
        lines.append(
            f"[{timestamp} · @{post.username} · likes {post.like_count} · "
            f"reposts {post.repost_count} · replies {post.reply_count} · id {post.post_id}] {text}"
        )
    return "\n".join(lines)
