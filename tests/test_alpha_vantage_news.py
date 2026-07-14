"""Structured Alpha Vantage news adapter and inclusive time-window tests."""

import pytest

from tradingagents.dataflows import alpha_vantage_news
from tradingagents.dataflows.evidence_models import validate_news_feed


@pytest.mark.unit
def test_ticker_news_preserves_body_relevance_and_inclusive_end(monkeypatch):
    captured = {}

    def request(function, params):
        captured.update(params)
        return {
            "feed": [{
                "title": "NVIDIA platform update",
                "source": "Example Wire",
                "time_published": "20260710T201500",
                "url": "https://example.com/nvda?utm_source=feed",
                "summary": "The company described its new platform.",
                "ticker_sentiment": [{"ticker": "NVDA"}],
            }]
        }

    monkeypatch.setattr(alpha_vantage_news, "_make_api_request", request)
    feed = alpha_vantage_news.get_news("NVDA", "2026-07-01", "2026-07-10")
    validated = validate_news_feed(
        feed,
        symbol="NVDA",
        expected_vendor="alpha_vantage",
        information_cutoff="2026-07-10T21:00:00+00:00",
    )

    assert captured["time_from"] == "20260701T0000"
    assert captured["time_to"] == "20260710T2359"
    assert validated.items[0].summary.startswith("The company")
    assert validated.items[0].symbols == ("NVDA",)
    assert validated.items[0].url == "https://example.com/nvda"


@pytest.mark.unit
def test_ticker_news_without_body_or_symbol_is_rejected(monkeypatch):
    monkeypatch.setattr(
        alpha_vantage_news,
        "_make_api_request",
        lambda *args: {"feed": [{
            "title": "Headline only", "source": "Example Wire",
            "time_published": "20260710T201500",
            "url": "https://example.com/headline", "summary": "",
            "ticker_sentiment": [{"ticker": "AAPL"}],
        }]},
    )
    feed = alpha_vantage_news.get_news("NVDA", "2026-07-01", "2026-07-10")
    with pytest.raises(ValueError, match="no news items"):
        validate_news_feed(
            feed,
            symbol="NVDA",
            expected_vendor="alpha_vantage",
            information_cutoff="2026-07-10T21:00:00+00:00",
        )
