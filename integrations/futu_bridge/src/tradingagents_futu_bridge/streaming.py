"""Progress reporting for streamed LLM responses without printing their content."""

from __future__ import annotations

import os
import sys
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import replace
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from tradingagents.llm_clients.openai_client import (
    DeepSeekChatOpenAI,
    OPENAI_COMPATIBLE_PROVIDERS,
    MinimaxChatOpenAI,
)


class StreamingMinimaxChatOpenAI(MinimaxChatOpenAI):
    """MiniMax client with optional streaming and objective-style prompt overlay."""

    def __init__(self, **kwargs):
        kwargs["streaming"] = _env_enabled("FUTU_BRIDGE_LLM_STREAMING", default=True)
        super().__init__(**kwargs)

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        if _env_enabled("FUTU_BRIDGE_OBJECTIVE_PROMPTS", default=True):
            payload.setdefault("messages", []).insert(
                0,
                {
                    "role": "system",
                    "content": OBJECTIVE_STYLE_INSTRUCTION,
                },
            )
        return payload


class StreamingDeepSeekChatOpenAI(DeepSeekChatOpenAI):
    """DeepSeek client with bridge-only streaming and objective style guidance."""

    def __init__(self, **kwargs):
        kwargs["streaming"] = _env_enabled("FUTU_BRIDGE_LLM_STREAMING", default=True)
        super().__init__(**kwargs)

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        if _env_enabled("FUTU_BRIDGE_OBJECTIVE_PROMPTS", default=True):
            payload.setdefault("messages", []).insert(
                0,
                {
                    "role": "system",
                    "content": OBJECTIVE_STYLE_INSTRUCTION,
                },
            )
        return payload


OBJECTIVE_STYLE_INSTRUCTION = """Use an objective, evidence-led analytical style.
- Separate reported facts, interpretations, and forward-looking estimates.
- Support material claims with the supplied source, date, units, and comparison period when available.
- Present supporting and contradicting evidence fairly. Analyze the evidence; do not argue to win a debate or defend a predetermined conclusion.
- Describe risks and opportunities in neutral, specific terms. Avoid sensational, promotional, alarmist, accusatory, or emotionally loaded wording.
- State assumptions, uncertainty, and what evidence could change the assessment. Do not present uncertain events as facts or imply guaranteed outcomes.
- If source material uses emotionally charged wording, summarize its factual meaning neutrally unless a short direct quote is essential.
- Do not invent facts, probabilities, sources, or certainty. Say when evidence is missing or conflicting.
- Follow the requested output schema and required rating labels exactly."""


def _env_enabled(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@contextmanager
def enable_bridge_llm_overrides(
    providers: set[str], *, streaming: bool, objective_prompts: bool
):
    """Temporarily enable bridge-only LLM behavior without changing mainline."""
    active = providers.intersection({"minimax", "minimax-cn", "deepseek"})
    if (not streaming and not objective_prompts) or not active:
        yield
        return

    originals = {
        name: OPENAI_COMPATIBLE_PROVIDERS[name]
        for name in active
        if name in OPENAI_COMPATIBLE_PROVIDERS
    }
    for name, spec in originals.items():
        OPENAI_COMPATIBLE_PROVIDERS[name] = replace(
            spec,
            chat_class=(
                StreamingDeepSeekChatOpenAI
                if name == "deepseek"
                else StreamingMinimaxChatOpenAI
            ),
        )
    try:
        yield
    finally:
        OPENAI_COMPATIBLE_PROVIDERS.update(originals)


class StreamingProgressHandler(BaseCallbackHandler):
    """Report request start, first token, continued output, and completion."""

    run_inline = True

    def __init__(self, report_every_chunks: int = 100):
        self.report_every_chunks = max(1, report_every_chunks)
        self._counts: dict[UUID, int] = defaultdict(int)
        self._started_at: dict[UUID, float] = {}
        self._last_chunk_at: dict[UUID, float] = {}
        self._max_gap: dict[UUID, float] = defaultdict(float)
        self._lock = threading.Lock()

    @staticmethod
    def _run_label(run_id: UUID | None) -> str:
        return str(run_id)[-6:] if run_id is not None else "llm"

    def on_llm_start(self, serialized, prompts, *, run_id: UUID, **kwargs) -> None:
        now = time.monotonic()
        with self._lock:
            self._counts[run_id] = 0
            self._started_at[run_id] = now
            self._last_chunk_at.pop(run_id, None)
            self._max_gap[run_id] = 0.0
        print(
            f"[模型 {self._run_label(run_id)}] 请求开始，等待首个响应片段…",
            file=sys.stderr,
            flush=True,
        )

    def on_llm_new_token(self, token: str, *, run_id: UUID, **kwargs) -> None:
        if not token:
            return
        now = time.monotonic()
        with self._lock:
            self._counts[run_id] += 1
            count = self._counts[run_id]
            started = self._started_at.get(run_id, now)
            last = self._last_chunk_at.get(run_id)
            gap = now - last if last is not None else 0.0
            self._max_gap[run_id] = max(self._max_gap[run_id], gap)
            self._last_chunk_at[run_id] = now
            max_gap = self._max_gap[run_id]
        if count == 1:
            message = f"首片段在 {now - started:.1f}s 到达，生成中"
        elif count % self.report_every_chunks == 0:
            message = f"持续输出 {count} 片段，最长间隔 {max_gap:.1f}s"
        else:
            return
        print(
            f"[模型 {self._run_label(run_id)}] {message}…",
            file=sys.stderr,
            flush=True,
        )

    def on_llm_end(self, response, *, run_id: UUID, **kwargs) -> None:
        now = time.monotonic()
        with self._lock:
            count = self._counts.pop(run_id, 0)
            started = self._started_at.pop(run_id, now)
            self._last_chunk_at.pop(run_id, None)
            max_gap = self._max_gap.pop(run_id, 0.0)
        print(
            f"[模型 {self._run_label(run_id)}] 响应完成（{count} 个片段，"
            f"{now - started:.1f}s，最长间隔 {max_gap:.1f}s）",
            file=sys.stderr,
            flush=True,
        )

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs) -> None:
        now = time.monotonic()
        with self._lock:
            count = self._counts.pop(run_id, 0)
            started = self._started_at.pop(run_id, now)
            self._last_chunk_at.pop(run_id, None)
            max_gap = self._max_gap.pop(run_id, 0.0)
        print(
            f"[模型 {self._run_label(run_id)}] 请求失败（{type(error).__name__}，"
            f"{now - started:.1f}s，{count} 片段，最长间隔 {max_gap:.1f}s）",
            file=sys.stderr,
            flush=True,
        )
