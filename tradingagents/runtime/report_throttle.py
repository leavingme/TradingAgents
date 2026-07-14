"""Deterministic coalescing for cumulative report-section updates."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator

from .events import AnalysisEvent


DEFAULT_REPORT_SECTION_THROTTLE_MS = 500
_TERMINAL_EVENTS = {"run_completed", "run_cancelled", "error"}


def report_section_throttle_seconds() -> float:
    """Return the server-owned report update interval.

    Invalid values fall back to the safe default.  Zero is supported for
    diagnostics and keeps the historical emit-every-update behaviour.
    """
    raw = os.environ.get(
        "TRADINGAGENTS_REPORT_SECTION_THROTTLE_MS",
        str(DEFAULT_REPORT_SECTION_THROTTLE_MS),
    )
    try:
        milliseconds = max(0, int(raw))
    except (TypeError, ValueError):
        milliseconds = DEFAULT_REPORT_SECTION_THROTTLE_MS
    return milliseconds / 1000


class ReportSectionThrottler:
    """Leading/trailing throttle keyed by ``run_id + section``.

    The first version stays immediately visible.  Updates inside the interval
    replace the pending version.  Pending versions are flushed when due,
    before their agent completes, before terminal events, and at end-of-stream.
    """

    def __init__(
        self,
        interval_seconds: float | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.interval_seconds = (
            report_section_throttle_seconds()
            if interval_seconds is None
            else max(0.0, interval_seconds)
        )
        self._clock = clock
        self._last_emitted: dict[tuple[str, str], float] = {}
        self._pending: dict[tuple[str, str], AnalysisEvent] = {}

    def push(self, event: AnalysisEvent) -> Iterator[AnalysisEvent]:
        now = self._clock()
        if event.type == "report_section":
            key = self._key(event)
            if key is None:
                yield event
                return
            last = self._last_emitted.get(key)
            if (
                last is None
                or self.interval_seconds == 0
                or now - last >= self.interval_seconds
            ):
                self._pending.pop(key, None)
                self._last_emitted[key] = now
                yield event
            else:
                self._pending[key] = event
            return

        if event.type in _TERMINAL_EVENTS:
            yield from self.flush()
        elif event.type == "agent_status" and isinstance(event.content, dict):
            if event.content.get("status") == "completed":
                yield from self.flush(agent=event.agent)
            else:
                yield from self.flush_due(now)
        else:
            yield from self.flush_due(now)
        yield event

    def flush_due(self, now: float | None = None) -> Iterator[AnalysisEvent]:
        current = self._clock() if now is None else now
        due = [
            key
            for key in self._pending
            if current - self._last_emitted.get(key, current) >= self.interval_seconds
        ]
        yield from self._flush_keys(due, current)

    def flush(self, *, agent: str | None = None) -> Iterator[AnalysisEvent]:
        now = self._clock()
        keys = [
            key
            for key, event in self._pending.items()
            if agent is None or event.agent == agent
        ]
        yield from self._flush_keys(keys, now)

    def _flush_keys(
        self, keys: list[tuple[str, str]], now: float
    ) -> Iterator[AnalysisEvent]:
        for key in keys:
            event = self._pending.pop(key, None)
            if event is None:
                continue
            self._last_emitted[key] = now
            yield event

    @staticmethod
    def _key(event: AnalysisEvent) -> tuple[str, str] | None:
        if not isinstance(event.content, dict):
            return None
        section = event.content.get("section")
        if not isinstance(section, str) or not section:
            return None
        return event.run_id, section
