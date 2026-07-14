"""Deterministic Polymarket adaptation, validation, rendering, and auditing."""

import copy
from dataclasses import replace
from datetime import datetime, timezone
import unittest
from unittest import mock

import pytest
import requests

import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config
from tradingagents.agents.utils.prediction_markets_tools import (
    get_prediction_markets as prediction_markets_tool,
)
from tradingagents.dataflows import interface, polymarket
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorUnavailableError,
)
from tradingagents.dataflows.evidence_models import (
    PredictionMarket,
    PredictionMarketFeed,
    PredictionOutcome,
    bind_prediction_market_call_id,
    prediction_source_id,
    render_prediction_market_feed,
    validate_prediction_market_feed,
)


def _market(
    question,
    prob,
    *,
    market_id,
    volume,
    end_date,
    closed=False,
    archived=False,
    active=True,
    wk=None,
):
    return {
        "id": market_id,
        "conditionId": f"condition-{market_id}",
        "question": question,
        "slug": question.lower().replace(" ", "-"),
        "outcomes": '["Yes", "No"]',
        "outcomePrices": f'["{prob}", "{round(1 - prob, 4)}"]',
        "volumeNum": volume,
        "endDate": end_date,
        "active": active,
        "closed": closed,
        "archived": archived,
        "oneWeekPriceChange": wk,
    }


_SEARCH = {
    "events": [
        {
            "id": "event-fed-2030",
            "title": "Federal Reserve decisions in 2030",
            "slug": "federal-reserve-decisions-2030",
            "endDate": "2030-12-31T00:00:00Z",
            "markets": [
                _market(
                    "Open big?", 0.76, market_id="market-big", volume=5_000_000,
                    end_date="2030-12-31T00:00:00Z", wk=-0.045,
                ),
                _market(
                    "Resolved already?", 1.0, market_id="market-closed",
                    volume=9_000_000, end_date="2030-12-31T00:00:00Z",
                    closed=True,
                ),
                _market(
                    "Past event?", 0.5, market_id="market-past", volume=8_000_000,
                    end_date="2020-01-01T00:00:00Z",
                ),
                _market(
                    "Open small?", 0.30, market_id="market-small", volume=1_000,
                    end_date="2030-06-30T00:00:00Z",
                ),
            ],
        }
    ]
}


def _validated(topic="anything", limit=10):
    with mock.patch.object(polymarket, "_request", return_value=_SEARCH):
        feed = polymarket.get_prediction_markets(topic, limit=limit)
    return validate_prediction_market_feed(feed, expected_vendor="polymarket")


def _feed_for_vendor(vendor: str, *, probability: float = 0.65):
    observed_at = "2026-07-14T04:00:00+00:00"
    event_id = "event-1"
    market_id = "market-1"
    return PredictionMarketFeed(
        topic="Fed cut",
        observed_at=observed_at,
        requested_limit=3,
        markets=(PredictionMarket(
            source_id=prediction_source_id(
                vendor=vendor, event_id=event_id, market_id=market_id
            ),
            event_id=event_id,
            event_title="Federal Reserve decision",
            market_id=market_id,
            condition_id="condition-1",
            question="Will the Fed cut?",
            slug="will-the-fed-cut",
            url="https://polymarket.com/event/will-the-fed-cut",
            expires_at="2030-12-31T00:00:00+00:00",
            observed_at=observed_at,
            outcomes=(
                PredictionOutcome("Yes", probability),
                PredictionOutcome("No", 1 - probability),
            ),
            volume=1000.0,
            one_week_probability_change=0.02,
            vendor=vendor,
        ),),
    )


@pytest.mark.unit
class PolymarketAdapterAndValidationTests(unittest.TestCase):
    def test_adapter_preserves_raw_ids_and_validator_filters_closed_and_expired(self):
        feed = _validated()
        self.assertEqual([market.question for market in feed.markets], [
            "Open big?", "Open small?",
        ])
        market = feed.markets[0]
        self.assertEqual(market.event_id, "event-fed-2030")
        self.assertEqual(market.market_id, "market-big")
        self.assertEqual(market.condition_id, "condition-market-big")
        self.assertEqual(market.expires_at, "2030-12-31T00:00:00+00:00")

    def test_volume_sort_limit_probability_and_stable_source_id(self):
        feed = _validated(limit=1)
        self.assertEqual(len(feed.markets), 1)
        market = feed.markets[0]
        self.assertEqual(market.question, "Open big?")
        self.assertEqual(market.outcomes[0].probability, 0.76)
        self.assertEqual(
            market.source_id,
            prediction_source_id(
                vendor="polymarket",
                event_id="event-fed-2030",
                market_id="market-big",
            ),
        )

    def test_invalid_id_expiry_probability_and_source_id_fail_closed(self):
        valid = _feed_for_vendor("polymarket")
        invalid_markets = (
            replace(valid.markets[0], event_id=""),
            replace(valid.markets[0], expires_at="2020-01-01T00:00:00+00:00"),
            replace(valid.markets[0], outcomes=(
                PredictionOutcome("Yes", 1.2), PredictionOutcome("No", -0.2),
            )),
            replace(valid.markets[0], source_id="prediction_forged000000000"),
        )
        for market in invalid_markets:
            with self.assertRaisesRegex(ValueError, "no prediction markets"):
                validate_prediction_market_feed(
                    replace(valid, markets=(market,)),
                    expected_vendor="polymarket",
                    now=datetime(2026, 7, 14, 5, tzinfo=timezone.utc),
                )

    def test_topic_and_information_cutoff_are_deterministic_gates(self):
        feed = _feed_for_vendor("polymarket")
        with self.assertRaisesRegex(ValueError, "topic does not match"):
            validate_prediction_market_feed(
                feed,
                expected_vendor="polymarket",
                expected_topic="recession",
                now=datetime(2026, 7, 14, 5, tzinfo=timezone.utc),
            )
        with self.assertRaisesRegex(ValueError, "exceeds information_cutoff"):
            validate_prediction_market_feed(
                feed,
                expected_vendor="polymarket",
                expected_topic="Fed cut",
                information_cutoff="2026-07-14T03:59:59+00:00",
                now=datetime(2026, 7, 14, 5, tzinfo=timezone.utc),
            )

    def test_renderer_includes_source_expiry_probability_and_vendor_call_id(self):
        feed = validate_prediction_market_feed(
            _feed_for_vendor("polymarket"),
            expected_vendor="polymarket",
            now=datetime(2026, 7, 14, 5, tzinfo=timezone.utc),
        )
        feed = bind_prediction_market_call_id(feed, "call-prediction-1")
        out = render_prediction_market_feed(feed)
        self.assertIn(feed.markets[0].source_id, out)
        self.assertIn("Yes 65.0%", out)
        self.assertIn("2030-12-31T00:00:00+00:00", out)
        self.assertIn("Vendor call ID: call-prediction-1", out)

    def test_no_matches_is_invalid_structured_evidence(self):
        with mock.patch.object(polymarket, "_request", return_value={"events": []}):
            feed = polymarket.get_prediction_markets("obscure ticker", limit=6)
        with self.assertRaisesRegex(ValueError, "no prediction markets"):
            validate_prediction_market_feed(feed, expected_vendor="polymarket")


@pytest.mark.unit
class PolymarketTemporalAndFailureTests(unittest.TestCase):
    def test_live_analysis_allows_snapshot_with_prior_market_data_date(self):
        with (
            mock.patch.object(
                polymarket, "_current_temporal_context", return_value=("live", None)
            ),
            mock.patch.object(polymarket, "_request", return_value=_SEARCH),
        ):
            feed = polymarket.get_prediction_markets("anything", limit=1)
        self.assertEqual(feed.topic, "anything")
        self.assertTrue(feed.observed_at.endswith("+00:00"))

    def test_point_in_time_analysis_rejects_live_snapshot_before_network(self):
        with (
            mock.patch.object(
                polymarket,
                "_current_temporal_context",
                return_value=("point_in_time", "2026-07-10T20:00:00+00:00"),
            ),
            mock.patch.object(polymarket, "_request") as request,
        ):
            with self.assertRaisesRegex(NoMarketDataError, "point-in-time evidence"):
                polymarket.get_prediction_markets("Fed rate cut")
        request.assert_not_called()

    def test_network_error_is_typed_instead_of_success_text(self):
        with mock.patch.object(
            polymarket, "_request", side_effect=requests.RequestException("boom")
        ):
            with self.assertRaisesRegex(VendorUnavailableError, "public-search failed"):
                polymarket.get_prediction_markets("Fed rate cut")


@pytest.mark.unit
class PolymarketRoutingTests(unittest.TestCase):
    def setUp(self):
        config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)

    def tearDown(self):
        config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)

    def test_category_routes_validates_and_binds_call_id(self):
        self.assertEqual(
            interface.get_category_for_method("get_prediction_markets"),
            "prediction_markets",
        )
        set_config({"data_vendors": {"prediction_markets": "polymarket"}})
        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_prediction_markets": {
                "polymarket": lambda *args, **kwargs: _feed_for_vendor("polymarket")
            }},
            clear=False,
        ):
            out = interface.route_to_vendor("get_prediction_markets", "Fed cut", 5)
        self.assertIsInstance(out, PredictionMarketFeed)
        self.assertTrue(out.markets[0].vendor_call_id)

    def test_invalid_optional_prediction_data_returns_unavailable_sentinel(self):
        invalid = _feed_for_vendor("polymarket", probability=1.2)
        set_config({"data_vendors": {"prediction_markets": "polymarket"}})
        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_prediction_markets": {"polymarket": lambda *args: invalid}},
            clear=False,
        ):
            out = interface.route_to_vendor("get_prediction_markets", "Fed cut", 5)
        self.assertIn("NO_DATA_AVAILABLE", out)

    def test_tool_safely_transports_optional_unavailable_status(self):
        with mock.patch(
            "tradingagents.agents.utils.prediction_markets_tools.route_to_vendor",
            return_value="DATA_UNAVAILABLE: optional prediction_markets failed",
        ):
            out = prediction_markets_tool.func("Fed cut", 3)
        self.assertIn("tradingagents.untrusted_data.v1", out)
        self.assertIn("DATA_UNAVAILABLE", out)


if __name__ == "__main__":
    unittest.main()
