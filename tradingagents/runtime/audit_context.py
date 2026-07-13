"""Run-scoped context propagated to data-vendor calls."""

from __future__ import annotations

from contextvars import ContextVar, Token


_run_id: ContextVar[str | None] = ContextVar("tradingagents_run_id", default=None)
_analysis_date: ContextVar[str | None] = ContextVar(
    "tradingagents_analysis_date", default=None
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
