"""StockTwits fetch degrades (never raises) on transport errors, including the
http.client chunked-transfer exceptions that are not OSErrors (#1024)."""

from __future__ import annotations

import http.client
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

from tradingagents.dataflows import stocktwits


def _raise(exc):
    class _Resp:
        def __enter__(self_inner):
            return self_inner

        def __exit__(self_inner, *a):
            return False

        def read(self_inner):
            raise exc
    return _Resp()


@pytest.mark.unit
class StockTwitsResilienceTests:
    @pytest.mark.parametrize(
        "exc",
        [
            http.client.IncompleteRead(b""),
            HTTPError("url", 503, "down", {}, None),
            TimeoutError("slow"),
        ],
    )
    def test_transport_errors_return_placeholder(self, exc):
        with patch.object(stocktwits, "urlopen", return_value=_raise(exc)):
            out = stocktwits.fetch_stocktwits_messages("NVDA")
        assert "unavailable" in out.lower()
        assert out.startswith("<stocktwits unavailable")

    def test_cloudflare_403_has_explicit_non_retryable_placeholder(self):
        exc = HTTPError("url", 403, "Forbidden", {"cf-mitigated": "challenge"}, None)
        with patch.object(stocktwits, "urlopen", side_effect=exc):
            out = stocktwits.fetch_stocktwits_messages("NVDA")

        assert out == (
            "<stocktwits unavailable: legacy endpoint requires browser challenge>"
        )
