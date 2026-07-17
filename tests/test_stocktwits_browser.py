from datetime import datetime, timezone
from unittest import mock

import pytest

from tradingagents.dataflows import interface, stocktwits_browser
from tradingagents.dataflows.errors import VendorNotConfiguredError
from tradingagents.dataflows.social_data import SocialFeed, SocialPost, validate_social_feed
from tradingagents.agents.utils import social_data_tools
from tradingagents.runtime.audit_context import (
    bind_analysis_mode,
    bind_run_id,
    reset_analysis_mode,
    reset_run_id,
)


RAW_PAYLOAD = {
    "symbol": {"symbol": "NVDA", "watchlist_count": 652556},
    "messages": [
        {
            "id": 42,
            "body": "$NVDA demand remains strong",
            "created_at": "2026-07-15T06:22:14Z",
            "user": {"id": 7, "username": "alice"},
            "entities": {"sentiment": {"basic": "Bullish"}},
            "likes": {"total": 3},
        },
        {
            "id": 43,
            "body": "invalid timestamp must not be fabricated",
            "created_at": "not-a-date",
            "user": {"id": 8, "username": "bob"},
            "entities": {},
        },
    ],
}


@pytest.mark.unit
def test_adapter_maps_raw_json_without_text_round_trip():
    observed_at = datetime(2026, 7, 15, 6, 23, tzinfo=timezone.utc)

    feed = stocktwits_browser._normalize_stocktwits_payload(
        RAW_PAYLOAD, ticker="nvda", limit=30, observed_at=observed_at
    )

    assert feed.source == "stocktwits_browser"
    assert feed.symbol == "NVDA"
    assert feed.observed_at == observed_at
    assert feed.watchlist_count == 652556
    assert len(feed.posts) == 1
    assert feed.posts[0].post_id == "42"
    assert feed.posts[0].sentiment == "Bullish"
    assert feed.posts[0].like_count == 3


@pytest.mark.unit
def test_social_validator_enforces_source_symbol_and_exact_cutoff():
    feed = SocialFeed(
        source="stocktwits_browser",
        symbol="NVDA",
        observed_at=datetime(2026, 7, 15, 6, 30, tzinfo=timezone.utc),
        posts=(
            SocialPost(
                post_id="before",
                text="$NVDA before cutoff",
                created_at=datetime(2026, 7, 15, 6, 20, tzinfo=timezone.utc),
                author_id="1",
                username="alice",
                sentiment="Bullish",
            ),
            SocialPost(
                post_id="after",
                text="$NVDA after cutoff",
                created_at=datetime(2026, 7, 15, 7, 0, tzinfo=timezone.utc),
                author_id="2",
                username="bob",
            ),
        ),
    )

    validated = validate_social_feed(
        feed,
        "2026-07-08",
        "2026-07-15",
        information_cutoff=datetime(2026, 7, 15, 6, 30, tzinfo=timezone.utc),
        expected_source="stocktwits_browser",
        expected_symbol="NVDA",
    )

    assert [post.post_id for post in validated.posts] == ["before"]
    with pytest.raises(ValueError, match="source mismatch"):
        validate_social_feed(
            feed,
            "2026-07-08",
            "2026-07-15",
            expected_source="bird",
        )


@pytest.mark.unit
def test_stocktwits_route_validates_and_records_selected_vendor(monkeypatch):
    feed = stocktwits_browser._normalize_stocktwits_payload(
        RAW_PAYLOAD,
        ticker="NVDA",
        limit=30,
        observed_at=datetime(2026, 7, 15, 6, 23, tzinfo=timezone.utc),
    )
    recorder = mock.Mock(return_value={"status": "available"})
    monkeypatch.setitem(
        interface.VENDOR_METHODS["get_stocktwits_messages"],
        "stocktwits_browser",
        lambda *_: feed,
    )
    monkeypatch.setattr(interface, "get_vendor", lambda *_: "stocktwits_browser")
    monkeypatch.setattr(interface, "_record_vendor_verification", recorder)

    result = interface.route_to_vendor(
        "get_stocktwits_messages", "NVDA", "2026-07-08", "2026-07-15"
    )

    assert isinstance(result, SocialFeed)
    assert result.posts[0].sentiment == "Bullish"
    assert recorder.call_args.kwargs["selected"] is True
    assert recorder.call_args.kwargs["result"] == result


@pytest.mark.unit
def test_stocktwits_tool_transports_rendered_feed_as_untrusted_data(monkeypatch):
    feed = stocktwits_browser._normalize_stocktwits_payload(
        RAW_PAYLOAD,
        ticker="NVDA",
        limit=30,
        observed_at=datetime(2026, 7, 15, 6, 23, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(social_data_tools, "route_to_vendor", lambda *args: feed)

    rendered = social_data_tools.get_stocktwits_messages.func(
        "NVDA", "2026-07-08", "2026-07-15"
    )

    assert '"schema": "tradingagents.untrusted_data.v1"' in rendered
    assert '"source": "stocktwits"' in rendered
    assert "Bullish 1 (100%)" in rendered


@pytest.mark.unit
def test_stocktwits_current_stream_fails_closed_for_point_in_time():
    run_token = bind_run_id("historical-run")
    mode_token = bind_analysis_mode("point_in_time")
    try:
        with pytest.raises(VendorNotConfiguredError, match="point-in-time"):
            stocktwits_browser.fetch_stocktwits_feed(
                "NVDA", "2026-07-01", "2026-07-08", timeout=1
            )
    finally:
        reset_analysis_mode(mode_token)
        reset_run_id(run_token)
