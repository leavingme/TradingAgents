import io
import urllib.error
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from tradingagents.dataflows import longbridge_mcp


def _valid_token() -> dict:
    return {
        "access_token": "sentinel-access-token",
        "expiry": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "base_url": "https://example.invalid",
    }


def _client(monkeypatch) -> longbridge_mcp.LongbridgeMCPClient:
    monkeypatch.setattr(longbridge_mcp, "_load_token", _valid_token)
    return longbridge_mcp.LongbridgeMCPClient()


def test_mcp_expiry_metadata_fails_closed():
    assert longbridge_mcp._is_expired({}) is True
    assert longbridge_mcp._is_expired({"expiry": "not-a-date"}) is True
    assert longbridge_mcp._is_expired({"expiry": "2999-01-01T00:00:00"}) is True
    assert longbridge_mcp._is_expired({
        "expiry": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    }) is True
    assert longbridge_mcp._is_expired(_valid_token()) is False


@pytest.mark.parametrize(
    "token,expected_status",
    [
        (None, "missing"),
        (["invalid"], "invalid"),
        ({"access_token": "token", "expiry": "invalid"}, "invalid"),
        (
            {
                "access_token": "token",
                "expiry": "2000-01-01T00:00:00+00:00",
            },
            "expired",
        ),
    ],
)
def test_mcp_token_status_never_treats_file_presence_as_configured(
    monkeypatch, token, expected_status
):
    monkeypatch.setattr(longbridge_mcp, "_load_token", lambda: token)
    status = longbridge_mcp.get_token_status()
    assert status["configured"] is False
    assert status["status"] == expected_status
    assert "access_token" not in status


def test_mcp_token_status_reports_only_safe_valid_metadata(monkeypatch):
    monkeypatch.setattr(longbridge_mcp, "_load_token", _valid_token)
    status = longbridge_mcp.get_token_status()
    assert status["configured"] is True
    assert status["status"] == "valid"
    assert status["expires_at"].endswith("+00:00")
    assert "sentinel-access-token" not in str(status)


@pytest.mark.parametrize(
    "token,error_type",
    [
        (None, longbridge_mcp.MCPNotActivatedError),
        (["not", "a", "mapping"], longbridge_mcp.MCPAuthError),
        ({"expiry": "2999-01-01T00:00:00+00:00"}, longbridge_mcp.MCPAuthError),
        ({"access_token": "token", "expiry": "invalid"}, longbridge_mcp.MCPAuthError),
    ],
)
def test_mcp_client_rejects_missing_or_invalid_token_without_path(
    monkeypatch, token, error_type
):
    monkeypatch.setattr(longbridge_mcp, "_load_token", lambda: token)
    with pytest.raises(error_type) as captured:
        longbridge_mcp.LongbridgeMCPClient()
    assert str(longbridge_mcp.TOKEN_PATH) not in str(captured.value)
    assert "access_token" not in str(captured.value)


@pytest.mark.parametrize(
    "status,error_type",
    [
        (401, longbridge_mcp.MCPAuthError),
        (403, longbridge_mcp.MCPAuthError),
        (500, longbridge_mcp.MCPTransportError),
    ],
)
def test_mcp_http_errors_discard_untrusted_body_and_reason(
    monkeypatch, status, error_type
):
    client = _client(monkeypatch)
    secret = "sentinel-mcp-secret"
    error = urllib.error.HTTPError(
        f"https://example.invalid/{secret}",
        status,
        f"reason-{secret}",
        hdrs=None,
        fp=io.BytesIO(f"body-{secret}".encode()),
    )
    monkeypatch.setattr(longbridge_mcp.urllib.request, "urlopen", mock.Mock(side_effect=error))

    with pytest.raises(error_type) as captured:
        client._post({"method": "tools/list"})

    message = str(captured.value)
    assert secret not in message
    assert "body-" not in message
    assert "reason-" not in message
    assert "https://" not in message


def test_mcp_network_and_malformed_response_errors_are_safe(monkeypatch):
    client = _client(monkeypatch)
    secret = "sentinel-mcp-secret"
    monkeypatch.setattr(
        longbridge_mcp.urllib.request,
        "urlopen",
        mock.Mock(side_effect=urllib.error.URLError(secret)),
    )
    with pytest.raises(longbridge_mcp.MCPTransportError) as network:
        client._post({"method": "tools/list"})
    assert secret not in str(network.value)

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return f"malformed-{secret}".encode()

    monkeypatch.setattr(longbridge_mcp.urllib.request, "urlopen", lambda *a, **k: _Response())
    with pytest.raises(longbridge_mcp.MCPTransportError) as malformed:
        client._post({"method": "tools/list"})
    assert secret not in str(malformed.value)


def test_mcp_json_rpc_error_discards_untrusted_message(monkeypatch):
    client = _client(monkeypatch)
    secret = "sentinel-mcp-secret"
    monkeypatch.setattr(
        client,
        "_post",
        lambda payload: {"error": {"code": -32000, "message": secret}},
    )

    with pytest.raises(longbridge_mcp.MCPTransportError) as captured:
        client._rpc("tools/list")

    assert str(captured.value) == (
        "Longbridge MCP JSON-RPC request failed (code=-32000)."
    )
    assert secret not in str(captured.value)


def test_mcp_tool_error_discards_untrusted_content():
    secret = "sentinel-mcp-secret"

    with pytest.raises(longbridge_mcp.MCPTransportError) as captured:
        longbridge_mcp._coerce_tool_result({
            "isError": True,
            "content": [{"type": "text", "text": secret}],
        })

    assert str(captured.value) == "Longbridge MCP tool returned an error result."
    assert secret not in str(captured.value)
