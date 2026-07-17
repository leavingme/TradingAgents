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
    sentiment: str | None = None


@dataclass(frozen=True)
class SocialFeed:
    source: str
    symbol: str
    posts: tuple[SocialPost, ...]
    observed_at: datetime | None = None
    watchlist_count: int | None = None


_SPAM = re.compile(
    r"(?:whatsapp|telegram|join (?:our|my)|link in (?:my )?bio|private (?:crypto|trading)|"
    r"trade alerts?|signals? daily|guaranteed returns?|dm me)",
    re.IGNORECASE,
)


def validate_social_feed(
    feed: SocialFeed,
    start_date: str,
    end_date: str,
    *,
    information_cutoff: datetime | None = None,
    expected_source: str | None = None,
    expected_symbol: str | None = None,
) -> SocialFeed:
    if not isinstance(feed, SocialFeed):
        raise TypeError("social vendor must return SocialFeed")
    if expected_source is not None and feed.source != expected_source:
        raise ValueError(
            f"social source mismatch: expected {expected_source!r}, got {feed.source!r}"
        )
    if expected_symbol is not None and feed.symbol.upper() != expected_symbol.upper():
        raise ValueError(
            f"social symbol mismatch: expected {expected_symbol!r}, got {feed.symbol!r}"
        )
    start = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc, hour=23, minute=59, second=59)
    if information_cutoff is not None:
        cutoff = information_cutoff
        if cutoff.tzinfo is None:
            raise ValueError("information_cutoff must include a timezone")
        end = min(end, cutoff.astimezone(timezone.utc))
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
            or post.sentiment not in {None, "Bullish", "Bearish"}
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
    observed_at = feed.observed_at
    if observed_at is not None:
        if observed_at.tzinfo is None:
            raise ValueError("social observed_at must include a timezone")
        if information_cutoff is not None and observed_at > information_cutoff:
            raise ValueError("social feed was observed after information_cutoff")
    if feed.watchlist_count is not None and feed.watchlist_count < 0:
        raise ValueError("social watchlist_count must not be negative")
    return SocialFeed(
        source=feed.source,
        symbol=feed.symbol,
        posts=tuple(valid),
        observed_at=observed_at,
        watchlist_count=feed.watchlist_count,
    )


def render_social_feed(feed: SocialFeed) -> str:
    source_label = "StockTwits" if feed.source == "stocktwits_browser" else f"X/Twitter via {feed.source}"
    heading = f"{source_label}: {len(feed.posts)} validated posts for {feed.symbol}"
    if feed.watchlist_count is not None:
        heading += f" (watchlist: {feed.watchlist_count:,})"
    lines = [heading]
    bullish = sum(post.sentiment == "Bullish" for post in feed.posts)
    bearish = sum(post.sentiment == "Bearish" for post in feed.posts)
    if bullish or bearish:
        labelled = bullish + bearish
        lines.append(
            f"Labelled sentiment: Bullish {bullish} ({round(100 * bullish / labelled)}%), "
            f"Bearish {bearish} ({round(100 * bearish / labelled)}%); "
            f"unlabelled {len(feed.posts) - labelled}"
        )
    for post in feed.posts:
        timestamp = post.created_at.astimezone(timezone.utc).isoformat()
        text = " ".join(post.text.split())
        sentiment = f" · {post.sentiment}" if post.sentiment else ""
        lines.append(
            f"[{timestamp} · @{post.username} · likes {post.like_count} · "
            f"reposts {post.repost_count} · replies {post.reply_count}{sentiment} · "
            f"id {post.post_id}] {text}"
        )
    return "\n".join(lines)
