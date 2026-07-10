#!/usr/bin/env python3
"""Probe whether a saved Bear Researcher report is rejected as next-turn input.

This is a focused diagnostic for provider-side input filters such as
``input new_sensitive``. By default the script only extracts and previews the
text. Pass ``--live`` to send a minimal summarization request to the configured
LLM provider.
"""

from __future__ import annotations

import argparse
import os
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client
from tradingagents.runtime.history import DB_PATH


SENSITIVE_TERMS = (
    "特朗普",
    "伊朗",
    "中东",
    "停火",
    "战争",
    "冲突",
    "制裁",
    "Trump",
    "Iran",
    "Middle East",
    "ceasefire",
    "war",
    "conflict",
    "sanction",
)

NOISY_TERMS = (
    "灵魂拷问",
    "接盘侠",
    "必跌",
    "必涨",
    "死猫跳",
    "绞肉机",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe whether Bear Researcher text is rejected as LLM input."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--run-id", help="Run id in runs.db, e.g. 0700.HK-e3248fa29602")
    source.add_argument("--text-file", type=Path, help="Plain text file to probe")
    parser.add_argument("--db", type=Path, help="SQLite DB path; auto-detected for --run-id when omitted")
    parser.add_argument("--section", default="bear_researcher", help="report_section name")
    parser.add_argument("--provider", help="LLM provider override")
    parser.add_argument("--model", help="LLM model override")
    parser.add_argument("--base-url", help="LLM base URL override")
    parser.add_argument("--max-chars", type=int, default=20000, help="Max chars of extracted text")
    parser.add_argument("--sanitize", action="store_true", help="Apply local keyword sanitization")
    parser.add_argument("--live", action="store_true", help="Actually call the LLM provider")
    parser.add_argument(
        "--split-live",
        choices=("section", "paragraph"),
        help="Call the provider once per section/paragraph to locate rejected chunks",
    )
    parser.add_argument(
        "--stop-on-reject",
        action="store_true",
        help="Stop split probing after the first rejected chunk",
    )
    parser.add_argument(
        "--ablate-defaults",
        action="store_true",
        help="Live-test default phrase removals to identify likely trigger phrases",
    )
    parser.add_argument("--show-text", action="store_true", help="Print the probed text")
    args = parser.parse_args()

    if args.run_id:
        db_path = resolve_db_path(args.run_id, args.db)
        text, run_provider = load_report_section(db_path, args.run_id, args.section)
    else:
        db_path = None
        text = args.text_file.read_text(encoding="utf-8")
        run_provider = None

    original_len = len(text)
    original_risk = risk_summary(text)
    if args.sanitize:
        text = sanitize_text(text)
    text = text[: args.max_chars]
    probed_risk = risk_summary(text)

    provider = args.provider or run_provider or DEFAULT_CONFIG["llm_provider"]
    model = args.model or default_model_for(provider)
    base_url = args.base_url if args.base_url is not None else DEFAULT_CONFIG.get("backend_url")

    print(
        json.dumps(
            {
                "source": args.run_id or str(args.text_file),
                "db": str(db_path) if db_path else None,
                "section": args.section if args.run_id else None,
                "original_chars": original_len,
                "probed_chars": len(text),
                "sanitized": args.sanitize,
                "original_risk_terms": original_risk,
                "probed_risk_terms": probed_risk,
                "provider": provider,
                "model": model,
                "base_url": base_url,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if args.show_text:
        print("\n--- PROBED TEXT START ---")
        print(text)
        print("--- PROBED TEXT END ---\n")
    else:
        print("\nPreview:")
        print(text[:1000])
        if len(text) > 1000:
            print("... [truncated preview]")

    if args.ablate_defaults:
        return probe_ablation(
            text=text,
            provider=provider,
            model=model,
            base_url=base_url,
        )

    if args.split_live:
        return probe_split_text(
            text=text,
            mode=args.split_live,
            provider=provider,
            model=model,
            base_url=base_url,
            stop_on_reject=args.stop_on_reject,
        )

    if not args.live:
        print("\nDry run only. Re-run with --live to call the provider.")
        return 0

    prompt = build_probe_prompt(text)
    try:
        llm = create_llm_client(provider=provider, model=model, base_url=base_url).get_llm()
        response = llm.invoke(prompt)
    except Exception as exc:  # provider SDK exception types differ
        print("\nPROBE_RESULT=rejected")
        print(f"error_type={type(exc).__name__}")
        print(f"error={exc}")
        return 2

    content = getattr(response, "content", response)
    print("\nPROBE_RESULT=accepted")
    print(str(content)[:2000])
    return 0


DEFAULT_ABLATIONS = (
    ("remove 非对称绞肉", "非对称绞肉"),
    ("remove 绞肉", "绞肉"),
    ("remove 赌博游戏", "赌博游戏"),
    ("remove 负期望值", "负期望值"),
    ("remove 负期望值的赌博游戏", "负期望值的赌博游戏"),
    ("remove 专业玩家", "专业玩家"),
    ("remove 买入", "买入"),
    ("remove 止损", "止损"),
    ("remove 买入 and 止损", ("买入", "止损")),
    ("remove 单日正常波动风险", "单日正常波动风险"),
    ("neutralize trading sentence", "在475港元附近买入、止损435港元，意味着你承受的**单日正常波动风险**就接近止损位的一半。"),
    ("neutralize final sentence", "专业玩家知道这叫什么——**这是一个负期望值的赌博游戏**。"),
)


def probe_ablation(
    *,
    text: str,
    provider: str,
    model: str,
    base_url: str | None,
) -> int:
    print("\nAblation probing default phrase removals...")
    llm = create_llm_client(provider=provider, model=model, base_url=base_url).get_llm()
    results = []

    for label, phrase_or_phrases in (("baseline", ()), *DEFAULT_ABLATIONS):
        variant = text
        phrases: tuple[str, ...]
        if isinstance(phrase_or_phrases, str):
            phrases = (phrase_or_phrases,)
        else:
            phrases = phrase_or_phrases
        for phrase in phrases:
            variant = variant.replace(phrase, "")

        try:
            response = llm.invoke(build_probe_prompt(variant))
        except Exception as exc:  # provider SDK exception types differ
            result = {
                "label": label,
                "chars": len(variant),
                "result": "rejected",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        else:
            content = getattr(response, "content", response)
            result = {
                "label": label,
                "chars": len(variant),
                "result": "accepted",
                "preview": str(content)[:240],
            }
        results.append(result)
        print(json.dumps(result, ensure_ascii=False))

    accepted = [item for item in results if item["result"] == "accepted"]
    print(
        json.dumps(
            {
                "tested": len(results),
                "accepted": [item["label"] for item in accepted],
                "rejected_count": len(results) - len(accepted),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if accepted else 2


def probe_split_text(
    *,
    text: str,
    mode: str,
    provider: str,
    model: str,
    base_url: str | None,
    stop_on_reject: bool,
) -> int:
    chunks = split_text(text, mode)
    print(f"\nSplit probing {len(chunks)} {mode} chunks...")
    llm = create_llm_client(provider=provider, model=model, base_url=base_url).get_llm()

    rejected = 0
    for index, (title, chunk) in enumerate(chunks, start=1):
        chunk_risk = risk_summary(chunk)
        print(
            json.dumps(
                {
                    "chunk": index,
                    "title": title,
                    "chars": len(chunk),
                    "risk_terms": chunk_risk,
                },
                ensure_ascii=False,
            )
        )
        try:
            response = llm.invoke(build_probe_prompt(chunk))
        except Exception as exc:  # provider SDK exception types differ
            rejected += 1
            print("PROBE_RESULT=rejected")
            print(f"error_type={type(exc).__name__}")
            print(f"error={exc}")
            if stop_on_reject:
                break
            continue

        content = getattr(response, "content", response)
        print("PROBE_RESULT=accepted")
        print(str(content)[:600])

    print(
        json.dumps(
            {
                "split_mode": mode,
                "chunks": len(chunks),
                "rejected": rejected,
                "accepted": len(chunks) - rejected,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 2 if rejected else 0


def load_report_section(db_path: Path, run_id: str, section: str) -> tuple[str, str | None]:
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        run = conn.execute("SELECT llm_provider FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not run:
            raise SystemExit(f"Run not found: {run_id}")

        rows = conn.execute(
            """
            SELECT agent, content, timestamp FROM events
            WHERE run_id=? AND event_type='report_section'
            ORDER BY id
            """,
            (run_id,),
        ).fetchall()

    matches: list[str] = []
    for row in rows:
        content = parse_content(row["content"])
        if not isinstance(content, dict):
            continue
        if content.get("section") == section:
            matches.append(str(content.get("text") or ""))

    if not matches:
        raise SystemExit(f"No report_section={section!r} found for run {run_id}")
    return matches[-1], run["llm_provider"]


def resolve_db_path(run_id: str, explicit: Path | None) -> Path:
    candidates = [explicit] if explicit else db_candidates()
    checked: list[str] = []
    for candidate in candidates:
        if candidate is None:
            continue
        checked.append(str(candidate))
        if not candidate.exists():
            continue
        with sqlite3.connect(candidate) as conn:
            row = conn.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row:
            return candidate
    raise SystemExit(
        "Run not found in DB candidates:\n"
        + "\n".join(f"- {path}" for path in checked)
        + f"\nrun_id={run_id}"
    )


def db_candidates() -> list[Path]:
    configured = os.environ.get("TRADINGAGENTS_DB") or os.environ.get("TRADINGAGENTS_WEBUI_DB")
    paths = [
        Path(configured) if configured else None,
        Path.home() / ".tradingagents" / "runs.db",
        DB_PATH,
        Path.cwd() / ".tradingagents" / "runs.db",
        Path.home() / ".tradingagents" / "webui_runs.db",
        Path.cwd() / ".tradingagents" / "webui_runs.db",
    ]
    deduped: list[Path] = []
    for path in paths:
        if path is not None and path not in deduped:
            deduped.append(path)
    return deduped


def split_text(text: str, mode: str) -> list[tuple[str, str]]:
    if mode == "paragraph":
        chunks = []
        for index, paragraph in enumerate(text.split("\n\n"), start=1):
            paragraph = paragraph.strip()
            if paragraph:
                chunks.append((f"paragraph {index}", paragraph))
        return chunks

    if mode != "section":
        raise ValueError(f"Unsupported split mode: {mode}")

    lines = text.splitlines()
    chunks: list[tuple[str, list[str]]] = []
    current_title = "preamble"
    current_lines: list[str] = []

    heading_re = re.compile(r"^##\s+(.+)$")
    for line in lines:
        match = heading_re.match(line)
        if match:
            if current_lines:
                chunks.append((current_title, current_lines))
            current_title = match.group(1).strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        chunks.append((current_title, current_lines))

    return [(title, "\n".join(chunk).strip()) for title, chunk in chunks if "\n".join(chunk).strip()]


def parse_content(raw: str | None) -> Any:
    if not raw:
        return None
    return json.loads(raw)


def default_model_for(provider: str) -> str:
    provider = provider.lower()
    if provider.startswith("minimax"):
        return "MiniMax-M3"
    return DEFAULT_CONFIG["quick_think_llm"]


def sanitize_text(text: str) -> str:
    kept: list[str] = []
    for paragraph in text.split("\n\n"):
        stripped = paragraph.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if any(term.lower() in lowered for term in SENSITIVE_TERMS):
            continue
        if any(term.lower() in lowered for term in NOISY_TERMS):
            continue
        kept.append(stripped)
    return "\n\n".join(kept) or text


def risk_summary(text: str) -> dict[str, int]:
    lowered = text.lower()
    terms = SENSITIVE_TERMS + NOISY_TERMS
    return {
        term: lowered.count(term.lower())
        for term in terms
        if lowered.count(term.lower()) > 0
    }


def build_probe_prompt(text: str) -> str:
    return f"""You are a neutral financial summarizer.

Task: Summarize the prior bearish investment argument below into exactly three
concise bullet points for a research manager. Keep only investment reasoning:
price levels, indicators, valuation assumptions, financial risks, and the final
stance. Do not add new facts.

Prior bearish investment argument:
<<<
{text}
>>>"""


if __name__ == "__main__":
    sys.exit(main())
