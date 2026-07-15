import pytest

from tradingagents.dataflows.evidence_models import (
    NewsFeed,
    NewsItem,
    render_news_feed,
    validate_news_feed,
    validate_report_citations,
)


def _item(**overrides):
    values = {
        "source_id": "",
        "title": "NVIDIA announces a new platform",
        "publisher": "Example Wire",
        "published_at": "2026-07-09T12:00:00+00:00",
        "url": "https://example.com/nvda-platform",
        "summary": "Product event.",
        "symbols": ("NVDA",),
        "vendor": "test",
    }
    values.update(overrides)
    return NewsItem(**values)


@pytest.mark.unit
def test_news_validation_binds_stable_source_id_and_renders_it():
    feed = validate_news_feed(NewsFeed(
        items=(_item(),), scope="ticker", requested_start="2026-07-01",
        requested_end="2026-07-10", query="NVDA",
    ), symbol="NVDA")
    assert feed.items[0].source_id.startswith("news_")
    assert feed.items[0].source_id in render_news_feed(feed)


@pytest.mark.unit
def test_news_validation_rejects_future_missing_url_and_wrong_symbol():
    for item in (
        _item(published_at="2026-07-11"),
        _item(url=""),
        _item(summary=""),
        _item(symbols=("AAPL",)),
    ):
        with pytest.raises(ValueError, match="no news items"):
            validate_news_feed(NewsFeed(
                items=(item,), scope="ticker", requested_start="2026-07-01",
                requested_end="2026-07-10", query="NVDA",
            ), symbol="NVDA")


def test_news_validation_enforces_exact_cutoff_and_canonical_url():
    cutoff = "2026-07-10T12:00:00+00:00"
    with pytest.raises(ValueError, match="no news items"):
        validate_news_feed(NewsFeed(
            items=(_item(published_at="2026-07-10T12:00:01+00:00"),),
            scope="ticker", requested_start="2026-07-01",
            requested_end="2026-07-10", query="NVDA",
        ), symbol="NVDA", expected_vendor="test", information_cutoff=cutoff)

    feed = validate_news_feed(NewsFeed(
        items=(_item(
            published_at="2026-07-10T11:59:59+00:00",
            url="https://EXAMPLE.com/nvda-platform?utm_source=x&article=1#section",
        ),), scope="ticker", requested_start="2026-07-01",
        requested_end="2026-07-10", query="NVDA",
    ), symbol="NVDA", expected_vendor="test", information_cutoff=cutoff)
    assert feed.items[0].url == "https://example.com/nvda-platform?article=1"


def test_news_validation_deduplicates_tracking_variants_and_checks_vendor():
    items = (
        _item(url="https://example.com/story?utm_source=one"),
        _item(url="https://EXAMPLE.com/story?utm_medium=two"),
    )
    feed = validate_news_feed(NewsFeed(
        items=items, scope="ticker", requested_start="2026-07-01",
        requested_end="2026-07-10", query="NVDA",
    ), symbol="NVDA", expected_vendor="test")
    assert len(feed.items) == 1
    assert feed.items[0].url == "https://example.com/story"
    with pytest.raises(ValueError, match="no news items"):
        validate_news_feed(NewsFeed(
            items=items, scope="ticker", requested_start="2026-07-01",
            requested_end="2026-07-10", query="NVDA",
        ), symbol="NVDA", expected_vendor="other")


@pytest.mark.unit
def test_material_claim_requires_known_source_id():
    source_id = "news_0123456789abcdefabcd"
    evidence = [f"[{source_id}] title"]
    assert validate_report_citations(
        f"NVIDIA announced a launch [{source_id}].", evidence
    )
    with pytest.raises(ValueError, match="must cite validated source_id"):
        validate_report_citations("NVIDIA announced a launch.", evidence)
    with pytest.raises(ValueError, match="unknown source_id"):
        validate_report_citations(
            "NVIDIA announced a launch [news_aaaaaaaaaaaaaaaaaaaa].", evidence
        )
    with pytest.raises(ValueError, match="missing a source_id"):
        validate_report_citations(
            f"Context [{source_id}].\n\nRevenue increased 85%.", evidence
        )
    with pytest.raises(ValueError, match="missing a source_id"):
        validate_report_citations(
            f"Context [{source_id}].\n\nThe target is $300.", evidence
        )


@pytest.mark.unit
def test_prediction_claim_accepts_only_known_prediction_source_id():
    source_id = "prediction_0123456789abcdefabcd"
    evidence = [f"[{source_id}] Fed probability 65%"]
    assert validate_report_citations(
        f"The market prices a 65% probability [{source_id}].", evidence
    )
    with pytest.raises(ValueError, match="unknown source_id"):
        validate_report_citations(
            "The market prices a 65% probability "
            "[prediction_aaaaaaaaaaaaaaaaaaaa].",
            evidence,
        )
