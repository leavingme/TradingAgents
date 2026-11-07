"""Translate Futu account-position responses into TradingAgents portfolio context."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable


def _as_rows(value: Any) -> list[dict[str, Any]]:
    """Unwrap common MCP content wrappers and return dictionary rows."""
    if isinstance(value, dict):
        if not value:
            return []
        for key in (
            "structuredContent", "result", "data", "accounts", "positions", "list",
            "acc_list", "position_list", "items", "rows",
        ):
            child = value.get(key)
            if key in value and value[key] is not None:
                return _as_rows(value[key])
        return [value]
    if isinstance(value, list):
        rows: list[dict[str, Any]] = []
        for child in value:
            rows.extend(_as_rows(child))
        return rows
    if isinstance(value, str):
        try:
            return _as_rows(json.loads(value))
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def unwrap_mcp_result(value: Any) -> Any:
    """Convert MCP structured content or text blocks to Python JSON values."""
    if not isinstance(value, dict):
        return value
    if value.get("isError"):
        raise ValueError("Futu MCP 返回错误；请检查授权状态和账号权限。")
    if value.get("structuredContent") is not None:
        return value["structuredContent"]
    content = value.get("content")
    if isinstance(content, list):
        values = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parsed = _as_rows(block["text"])
                if parsed:
                    values.extend(parsed)
        if values:
            return values
    return value


def _field(row: dict[str, Any], *names: str) -> Any:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def normalize_futu_symbol(code: Any) -> str:
    """Map Futu venue-prefixed codes to the Yahoo-style symbols used here."""
    value = str(code or "").strip().upper()
    match = re.fullmatch(r"HK\.(\d{1,5})", value)
    if match:
        return f"{int(match.group(1)):04d}.HK"
    match = re.fullmatch(r"US\.([A-Z][A-Z0-9.\-]*)", value)
    if match:
        return match.group(1)
    return value


def _is_real_account(row: dict[str, Any]) -> bool:
    raw_env = _field(row, "trd_env", "trade_env", "environment")
    env = str(raw_env if raw_env is not None else "").upper()
    return env in {"REAL", "REAL_ACCOUNT", "LIVE", "0"}


def real_accounts(response: Any) -> list[dict[str, Any]]:
    result = unwrap_mcp_result(response)
    rows = _as_rows(result)
    return [row for row in rows if _field(row, "acc_id", "account_id") is not None and _is_real_account(row)]


@dataclass(frozen=True)
class Holding:
    ticker: str
    quantity: float
    average_price: float | None
    currency: str | None


@dataclass(frozen=True)
class FutuPortfolioSnapshot:
    """Duck-typed portfolio accepted by ``TradingAgentsGraph.propagate``."""

    holdings: tuple[Holding, ...]
    as_of: str

    def render(self, ticker: str) -> str:
        symbol = normalize_futu_symbol(ticker)
        selected = [holding for holding in self.holdings if holding.ticker == symbol]
        others = [holding for holding in self.holdings if holding.ticker != symbol]
        lines = [
            f"Current Futu account snapshot captured at {self.as_of}; "
            "this is not a historical holdings snapshot."
        ]
        if selected:
            for holding in selected:
                avg = f", average cost {holding.average_price:,.4f}" if holding.average_price is not None else ""
                currency = f" {holding.currency}" if holding.currency else ""
                lines.append(f"- Current position in {symbol}: {holding.quantity:,.4f} units{avg}{currency}")
        else:
            lines.append(f"- No current position in {symbol}")
        if others:
            text = ", ".join(
                f"{h.ticker} {h.quantity:,.4f}"
                f"{f', average cost {h.average_price:,.4f}' if h.average_price is not None else ''}"
                f"{' ' + h.currency if h.currency else ''}"
                for h in others
            )
            lines.append("- Other positions: " + text)
        return "Portfolio context (latest current Futu snapshot):\n" + "\n".join(lines)

    def fingerprint(self) -> str:
        material = json.dumps(
            {"as_of": self.as_of, "holdings": [h.__dict__ for h in self.holdings]},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(material.encode()).hexdigest()[:12]


def holdings_from_positions(responses: Iterable[Any], as_of: str) -> FutuPortfolioSnapshot:
    """Normalize one or more account_positions responses, combining duplicates."""
    grouped: dict[tuple[str, str | None], list[float]] = {}
    for response in responses:
        rows = _as_rows(unwrap_mcp_result(response))
        for row in rows:
            code = _field(row, "code", "ticker", "symbol", "stock_code")
            quantity = _number(_field(row, "qty", "quantity", "position_qty", "stock_qty"))
            if code is None or quantity is None:
                raise ValueError(
                    "无法识别 Futu 持仓响应字段；为避免把未解析的数据当作空仓，已停止分析。"
                )
            ticker = normalize_futu_symbol(code)
            if not ticker:
                continue
            currency = _field(row, "currency", "quote_currency", "cost_currency")
            currency = str(currency).upper() if currency else None
            average = _number(_field(row, "cost_price", "average_price", "avg_price"))
            key = ticker, currency
            grouped.setdefault(key, [0.0, 0.0, 0.0])
            # Weighted cost across accounts when both quantities and cost exist.
            total, cost_value, cost_qty = grouped[key]
            grouped[key][0] = total + quantity
            if average is not None and quantity > 0:
                grouped[key][1] = cost_value + average * quantity
                grouped[key][2] = cost_qty + quantity

    holdings = tuple(
        Holding(ticker, values[0], values[1] / values[2] if values[2] else None, currency)
        for (ticker, currency), values in sorted(grouped.items())
    )
    return FutuPortfolioSnapshot(holdings=holdings, as_of=as_of)
