from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tradingagents.dataflows import bird
from tradingagents.dataflows.errors import VendorNotConfiguredError, VendorRateLimitError
from tradingagents.dataflows.social_data import (
    SocialFeed,
    SocialPost,
    render_social_feed,
    validate_social_feed,
)


def _post(post_id, text, date="2026-07-10T12:00:00+00:00"):
    return SocialPost(
        post_id=post_id,
        text=text,
        created_at=datetime.fromisoformat(date),
        author_id="author-1",
        username="investor",
        like_count=4,
    )


def test_validator_filters_future_duplicate_and_promotional_posts():
    feed = SocialFeed(source="bird", symbol="NVDA", posts=(
        _post("1", "$NVDA demand remains strong"),
        _post("1", "duplicate"),
        _post("2", "Join our private WhatsApp crypto community"),
        _post("3", "future", "2026-07-12T00:00:00+00:00"),
    ))

    validated = validate_social_feed(feed, "2026-07-04", "2026-07-11")

    assert [post.post_id for post in validated.posts] == ["1"]
    rendered = render_social_feed(validated)
    assert "@investor" in rendered
    assert "likes 4" in rendered


def test_bird_adapter_maps_json_without_flattening(monkeypatch):
    monkeypatch.setattr(bird.shutil, "which", lambda _name: "/usr/bin/bird")
    monkeypatch.setattr(bird.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0,
        stderr="",
        stdout='[{"id":"42","text":"$NVDA update","createdAt":"Fri Jul 10 12:00:00 +0000 2026","replyCount":1,"retweetCount":2,"likeCount":3,"author":{"username":"alice"},"authorId":"7"}]',
    ))

    feed = bird.get_social_posts("NVDA", "2026-07-04", "2026-07-11")

    assert feed.posts[0].post_id == "42"
    assert feed.posts[0].username == "alice"
    assert feed.posts[0].repost_count == 2


def test_bird_adapter_classifies_auth_and_rate_limit(monkeypatch):
    monkeypatch.setattr(bird.shutil, "which", lambda _name: "/usr/bin/bird")
    monkeypatch.setattr(bird.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=1, stderr="authentication cookie missing", stdout="",
    ))
    with pytest.raises(VendorNotConfiguredError):
        bird.get_social_posts("NVDA", "2026-07-04", "2026-07-11")

    monkeypatch.setattr(bird.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=1, stderr="429 rate limit", stdout="",
    ))
    with pytest.raises(VendorRateLimitError):
        bird.get_social_posts("NVDA", "2026-07-04", "2026-07-11")


def test_social_route_returns_only_validated_unified_model(monkeypatch):
    from tradingagents.dataflows import interface

    raw = SocialFeed(source="bird", symbol="NVDA", posts=(
        _post("valid", "$NVDA product demand update"),
        _post("spam", "Join my Telegram for trade signals daily"),
    ))
    monkeypatch.setitem(interface.VENDOR_METHODS["get_social_posts"], "bird", lambda *_: raw)
    monkeypatch.setattr(interface, "get_vendor", lambda *_: "bird")

    result = interface.route_to_vendor(
        "get_social_posts", "NVDA", "2026-07-04", "2026-07-11"
    )

    assert isinstance(result, SocialFeed)
    assert [post.post_id for post in result.posts] == ["valid"]


def test_reddit_social_setting_controls_sentiment_prefetch(monkeypatch):
    from tradingagents.agents.analysts import sentiment_analyst

    monkeypatch.setattr(
        sentiment_analyst,
        "get_config",
        lambda: {"data_vendors": {"social_data": "bird, reddit"}},
    )
    assert sentiment_analyst._social_source_enabled("reddit") is True

    monkeypatch.setattr(
        sentiment_analyst,
        "get_config",
        lambda: {"data_vendors": {"social_data": "bird"}},
    )
    assert sentiment_analyst._social_source_enabled("reddit") is False


def test_stocktwits_default_block_does_not_claim_live_data():
    from tradingagents.agents.analysts import sentiment_analyst

    block = sentiment_analyst._stocktwits_disabled_block()

    assert block.startswith("<StockTwits disabled:")
    assert "browser challenge" in block
