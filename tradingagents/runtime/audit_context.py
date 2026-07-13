"""Run-scoped context propagated to data-vendor calls."""

from __future__ import annotations

from contextvars import ContextVar, Token
from datetime import date, datetime


_run_id: ContextVar[str | None] = ContextVar("tradingagents_run_id", default=None)
_analysis_date: ContextVar[str | None] = ContextVar(
    "tradingagents_analysis_date", default=None
)
_analysis_mode: ContextVar[str] = ContextVar(
    "tradingagents_analysis_mode", default="live"
)
_information_cutoff: ContextVar[str | None] = ContextVar(
    "tradingagents_information_cutoff", default=None
)


def current_run_id() -> str | None:
    return _run_id.get()


def bind_run_id(run_id: str) -> Token:
    return _run_id.set(run_id)


def reset_run_id(token: Token) -> None:
    _run_id.reset(token)


def current_analysis_date() -> str | None:
    return _analysis_date.get()


def bind_analysis_date(analysis_date: str) -> Token:
    return _analysis_date.set(str(analysis_date))


def reset_analysis_date(token: Token) -> None:
    _analysis_date.reset(token)


def current_analysis_mode() -> str:
    return _analysis_mode.get()


def bind_analysis_mode(analysis_mode: str) -> Token:
    return _analysis_mode.set(analysis_mode)


def reset_analysis_mode(token: Token) -> None:
    _analysis_mode.reset(token)


def current_information_cutoff() -> str | None:
    return _information_cutoff.get()


def bind_information_cutoff(information_cutoff: str | None) -> Token:
    return _information_cutoff.set(information_cutoff)


def reset_information_cutoff(token: Token) -> None:
    _information_cutoff.reset(token)


def validate_temporal_context(
    market_data_date: str,
    analysis_mode: str,
    information_cutoff: str | None,
) -> None:
    """Validate the distinct market-data and information time axes."""
    try:
        market_date = date.fromisoformat(str(market_data_date))
    except ValueError as exc:
        raise ValueError("analysis_date must be YYYY-MM-DD") from exc
    if analysis_mode not in {"live", "point_in_time"}:
        raise ValueError("analysis_mode must be 'live' or 'point_in_time'")
    if analysis_mode == "live":
        if information_cutoff is not None:
            raise ValueError("live analysis uses call-time information; omit information_cutoff")
        return
    if not information_cutoff:
        raise ValueError("point_in_time analysis requires information_cutoff")
    try:
        cutoff = datetime.fromisoformat(information_cutoff.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("information_cutoff must be an ISO-8601 timestamp") from exc
    if cutoff.tzinfo is None:
        raise ValueError("information_cutoff must include a timezone")
    if cutoff.date() < market_date:
        raise ValueError("information_cutoff cannot precede analysis_date")
