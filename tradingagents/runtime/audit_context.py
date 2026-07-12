"""Run-scoped context propagated to data-vendor calls."""

from __future__ import annotations

from contextvars import ContextVar, Token


_run_id: ContextVar[str | None] = ContextVar("tradingagents_run_id", default=None)


def current_run_id() -> str | None:
    return _run_id.get()


def bind_run_id(run_id: str) -> Token:
    return _run_id.set(run_id)


def reset_run_id(token: Token) -> None:
    _run_id.reset(token)
