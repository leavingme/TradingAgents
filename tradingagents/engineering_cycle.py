"""Repeatable analysis -> review -> P0 remediation engineering cycle."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

# Engineering cycles must use one explicit database regardless of whether HOME
# is writable in the current sandbox/CI namespace.
REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINEERING_DB = REPO_ROOT / ".tradingagents" / "engineering-cycle-runs.db"

from tradingagents.runtime import AnalysisRequest, history_store, run_analysis_stream
from tradingagents.runtime.history import RunHistoryStore
from tradingagents.runtime.stats_handler import StatsCallbackHandler


SCHEMA_VERSION = "tradingagents.engineering-cycle.v1"
DEFAULT_ROOT = Path.cwd() / ".tradingagents" / "engineering_cycles"
TERMINAL_RUN_STATES = {"completed", "review_required", "unavailable", "failed", "cancelled"}
P0_RESOLVED = "resolved"
AUTOMATIC_FINDING_IDS = {
    "P0-RUN-FAILURE", "P0-NO-VALID-DECISION",
    "P0-NONLONG-EXECUTABLE-NUMBERS", "P0-MISSING-VENDOR-AUDIT",
    "P0-CURRENCY-UNIT-DRIFT",
    "P0-INCOMPLETE-VENDOR-PROVENANCE", "P1-VENDOR-FALLBACK",
    "P1-MISSING-LLM-STATS", "P1-HIGH-CONTEXT-COST",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_analysis_date(today: date | None = None) -> str:
    """Return the most recent completed weekday, never today's forming bar."""
    candidate = (today or date.today()) - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate.isoformat()


def cycle_dir(run_id: str, root: Path = DEFAULT_ROOT) -> Path:
    safe = "".join(ch for ch in run_id if ch.isalnum() or ch in "-_.")
    if not safe or safe != run_id:
        raise ValueError("run_id contains unsafe path characters")
    path = root / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_engineering_settings() -> dict[str, Any]:
    """Load the same server-owned LLM choices used by Web, with safe fallbacks."""
    from tradingagents.default_config import DEFAULT_CONFIG

    settings: dict[str, Any] = {}
    config_path = Path(
        os.environ.get(
            "TRADINGAGENTS_WEB_CONFIG_PATH",
            str(Path.home() / ".tradingagents" / "web_config.json"),
        )
    ).expanduser()
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        if isinstance(payload.get("settings"), dict):
            settings = payload["settings"]
    except (OSError, json.JSONDecodeError):
        pass
    return {
        "llm_provider": settings.get("llm_provider") or DEFAULT_CONFIG["llm_provider"],
        "quick_think_llm": (
            settings.get("quick_think_llm") or DEFAULT_CONFIG["quick_think_llm"]
        ),
        "deep_think_llm": (
            settings.get("deep_think_llm") or DEFAULT_CONFIG["deep_think_llm"]
        ),
        "backend_url": settings.get("backend_url") or DEFAULT_CONFIG.get("backend_url"),
        "output_language": (
            settings.get("output_language") or DEFAULT_CONFIG.get("output_language")
        ),
    }


def run_baseline(
    *,
    symbol: str = "NVDA",
    analysis_date: str | None = None,
    root: Path = DEFAULT_ROOT,
    selected_analysts: tuple[str, ...] = ("market", "social", "news", "fundamentals"),
    research_depth: int = 1,
    analysis_mode: str = "live",
    information_cutoff: str | None = None,
    parent_run_id: str | None = None,
) -> str:
    """Run the audited baseline and persist a cycle manifest."""
    if Path(history_store._db_path).resolve() != ENGINEERING_DB.resolve():
        raise RuntimeError(
            "engineering cycle database is not bound; use scripts/engineering_cycle.py"
        )
    settings = load_engineering_settings()
    stats_handler = StatsCallbackHandler()
    request = AnalysisRequest(
        ticker=symbol.upper(),
        analysis_date=analysis_date or default_analysis_date(),
        analysis_mode=analysis_mode,
        information_cutoff=information_cutoff,
        selected_analysts=selected_analysts,
        research_depth=research_depth,
        callbacks=(stats_handler,),
        **settings,
    )
    directory = cycle_dir(request.run_id, root)
    manifest = {
        "schema": SCHEMA_VERSION,
        "run_id": request.run_id,
        "phase": "running",
        "created_at": _now(),
        "request": {
            "ticker": request.ticker,
            "analysis_date": request.analysis_date,
            "analysis_mode": request.analysis_mode,
            "information_cutoff": request.information_cutoff,
            "selected_analysts": list(request.selected_analysts),
            "research_depth": request.research_depth,
        },
        "effective_llm_config": settings,
        "database": str(ENGINEERING_DB),
        "parent_run_id": parent_run_id,
    }
    _write_json(directory / "cycle.json", manifest)
    try:
        for event in run_analysis_stream(request):
            if event.type == "agent_status":
                print(
                    f"[agent_status] {event.agent}: "
                    f"{(event.content or {}).get('status')}",
                    flush=True,
                )
            elif event.type == "error":
                print(f"[error] {(event.content or {}).get('error')}", flush=True)
            elif event.type == "run_completed":
                content = event.content or {}
                print(
                    "[run_completed] "
                    f"decision_status={content.get('decision_status')} "
                    f"report_path={content.get('report_path')}",
                    flush=True,
                )
        record = history_store.get_run(request.run_id) or {}
        manifest.update({
            "phase": "run_finished",
            "run_status": record.get("status", "unavailable"),
            "decision_status": record.get("decision_status", "unavailable"),
            "finished_at": _now(),
        })
    except Exception as exc:
        manifest.update({
            "phase": "run_failed",
            "run_status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "finished_at": _now(),
        })
        _write_json(directory / "cycle.json", manifest)
        raise
    _write_json(directory / "cycle.json", manifest)
    if parent_run_id:
        parent_dir = cycle_dir(parent_run_id, root)
        parent_path = parent_dir / "cycle.json"
        parent = json.loads(parent_path.read_text(encoding="utf-8"))
        children = list(parent.get("remediation_runs") or [])
        if request.run_id not in children:
            children.append(request.run_id)
        parent["remediation_runs"] = children
        _write_json(parent_path, parent)
    return request.run_id


def rerun_baseline(parent_run_id: str, *, root: Path = DEFAULT_ROOT) -> str:
    parent_path = cycle_dir(parent_run_id, root) / "cycle.json"
    parent = json.loads(parent_path.read_text(encoding="utf-8"))
    request = parent.get("request") or {}
    return run_baseline(
        symbol=request.get("ticker", "NVDA"),
        analysis_date=request.get("analysis_date"),
        selected_analysts=tuple(
            request.get("selected_analysts")
            or ("market", "social", "news", "fundamentals")
        ),
        research_depth=int(request.get("research_depth") or 1),
        analysis_mode=request.get("analysis_mode", "live"),
        information_cutoff=request.get("information_cutoff"),
        parent_run_id=parent_run_id,
        root=root,
    )


def _last_stats(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(events):
        if event.get("type") == "stats" and isinstance(event.get("content"), dict):
            return dict(event["content"])
    return {}


def _finding(
    finding_id: str,
    severity: str,
    title: str,
    evidence: str,
    proposed_solution: str,
    acceptance: str,
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "origin": "automatic",
        "severity": severity,
        "title": title,
        "evidence": evidence,
        "root_cause": "待工程复盘确认",
        "proposed_solution": proposed_solution,
        "acceptance": acceptance,
        "status": "open",
        "implementation_evidence": "",
        "verification": "",
    }


def detect_findings(
    run: dict[str, Any], vendor_calls: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Detect only evidence-backed issues; human reviewers may append more."""
    events = list(run.get("events") or [])
    findings: list[dict[str, Any]] = []
    status = str(run.get("status") or "unavailable")
    decision_status = str(run.get("decision_status") or "unavailable")
    completed = next(
        (
            event.get("content") for event in reversed(events)
            if event.get("type") == "run_completed" and isinstance(event.get("content"), dict)
        ),
        {},
    )
    decision_text = str(completed.get("decision") or "")
    trusted_evidence_sections = {
        "market_report",
        "sentiment_report",
        "news_report",
        "fundamentals_report",
    }
    report_sections = [
        str((event.get("content") or {}).get("text") or "")
        for event in events
        if event.get("type") == "report_section"
        and (event.get("content") or {}).get("section") in trusted_evidence_sections
    ]
    if status in {"failed", "cancelled"} or any(e.get("type") == "error" for e in events):
        errors = [e.get("content") for e in events if e.get("type") == "error"]
        findings.append(_finding(
            "P0-RUN-FAILURE", "P0", "基准分析未可靠完成",
            f"run_status={status}; errors={errors}",
            "定位首个失败的数据域/Agent，修复后使用同一输入重新运行。",
            "相同 NVDA 输入产生 run_completed，且无 error 事件。",
        ))
    if decision_status != "validated":
        findings.append(_finding(
            "P0-NO-VALID-DECISION", "P0", "没有通过验证的最终决策",
            f"decision_status={decision_status}",
            "沿 Trader/Portfolio Manager 的结构化输出和确定性门禁定位根因。",
            "重跑后 decision_status=validated；不得通过伪装 Hold 绕过。",
        ))
    elif any(
        f"**Rating**: {rating}" in decision_text
        for rating in ("Hold", "Underweight", "Sell")
    ):
        from tradingagents.agents.schemas import contains_unverified_non_long_execution

        if contains_unverified_non_long_execution(decision_text):
            findings.append(_finding(
                "P0-NONLONG-EXECUTABLE-NUMBERS", "P0",
                "非多头决策包含未验证的执行数字",
                "validated Hold/Underweight/Sell report contains numeric execution guidance",
                "扩展非执行型 prose 清理器；不得放松 Buy/Overweight 的结构化门禁。",
                "非多头报告不含入场/减仓/清仓/回补/对冲/行权价等执行数字。",
            ))
    if decision_status == "validated" and report_sections:
        from tradingagents.agents.schemas import unsupported_currency_amounts

        unsupported = unsupported_currency_amounts(
            decision_text,
            "\n".join(report_sections),
        )
        if unsupported:
            findings.append(_finding(
                "P0-CURRENCY-UNIT-DRIFT", "P0",
                "最终决策包含无法追溯的货币单位漂移",
                f"unsupported normalized currency amounts={unsupported}",
                "在 Portfolio Manager 渲染边界按 USD 绝对值统一 M/B/T/亿/万亿并拒绝新增数值。",
                "同输入重跑通过；最终报告的全部货币数字均可与上游证据在舍入容差内对齐。",
            ))
    if not vendor_calls:
        findings.append(_finding(
            "P0-MISSING-VENDOR-AUDIT", "P0", "运行缺少 vendor 审计账本",
            "run_vendor_calls 为空",
            "确保所有正式入口绑定 run_id，且审计写入失败时硬失败。",
            "核心数据调用均有 call_id/attempt/selected/result_hash。",
        ))
    else:
        selected = [call for call in vendor_calls if call.get("selected")]
        missing_hash = [call.get("call_id") for call in selected if not call.get("result_hash")]
        if missing_hash:
            findings.append(_finding(
                "P0-INCOMPLETE-VENDOR-PROVENANCE", "P0", "选中数据缺少结果指纹",
                f"call_ids={missing_hash}",
                "在统一 router 成功边界补齐不可变结果摘要与 hash。",
                "所有 selected vendor attempt 均具有非空 result_hash。",
            ))
        fallback_calls = Counter(
            call.get("call_id") for call in vendor_calls if int(call.get("attempt") or 0) > 1
        )
        if fallback_calls:
            findings.append(_finding(
                "P1-VENDOR-FALLBACK", "P1", "运行发生 vendor fallback",
                f"fallback_call_count={len(fallback_calls)}",
                "检查首选 vendor 的失败类别、延迟和覆盖率；保留正确 fallback。",
                "明确根因并证明 fallback 结果通过同一 validator。",
            ))

    stats = _last_stats(events)
    if not stats:
        findings.append(_finding(
            "P1-MISSING-LLM-STATS", "P1", "缺少运行级 LLM/tool/token 统计",
            "未找到 stats 事件",
            "确保正式入口安装 StatsCallbackHandler 并持久化最终快照。",
            "review 能展示非零调用量和 token 统计。",
        ))
    elif int(stats.get("tokens_in") or 0) > 150_000:
        findings.append(_finding(
            "P1-HIGH-CONTEXT-COST", "P1", "输入 token 量过高",
            f"tokens_in={stats.get('tokens_in')}",
            "分析重复报告、工具结果和辩论上下文，制定有证据的压缩方案。",
            "同配置重跑 tokens_in 降低且结论证据未丢失。",
        ))
    return findings


def build_review(run_id: str, *, root: Path = DEFAULT_ROOT, store=history_store) -> Path:
    """Export persisted execution evidence and create review/P0 artifacts."""
    run = store.get_run(run_id)
    if run is None:
        raise ValueError(f"run not found: {run_id}")
    if run.get("status") not in TERMINAL_RUN_STATES:
        raise ValueError(f"run is not terminal: {run.get('status')}")
    vendor_calls = store.get_vendor_calls(run_id)
    directory = cycle_dir(run_id, root)
    findings_path = directory / "findings.json"
    existing_findings: list[dict[str, Any]] = []
    existing_acknowledgement: dict[str, Any] | None = None
    if findings_path.exists():
        existing = json.loads(findings_path.read_text(encoding="utf-8"))
        existing_findings = list(existing.get("findings") or [])
        if isinstance(existing.get("review_acknowledgement"), dict):
            existing_acknowledgement = dict(existing["review_acknowledgement"])
    detected = detect_findings(run, vendor_calls)
    existing_by_id = {item["id"]: item for item in existing_findings}
    findings = [existing_by_id.get(item["id"], item) for item in detected]
    detected_ids = {item["id"] for item in detected}
    findings.extend(
        item for item in existing_findings
        if item["id"] not in detected_ids and (
            item.get("id") not in AUTOMATIC_FINDING_IDS
            or item.get("status") == P0_RESOLVED
        )
    )
    findings_payload = {
        "schema": SCHEMA_VERSION,
        "run_id": run_id,
        "reviewed_at": _now(),
        "findings": findings,
    }
    if existing_acknowledgement:
        findings_payload["review_acknowledgement"] = existing_acknowledgement
    _write_json(findings_path, findings_payload)
    _write_json(directory / "execution-evidence.json", {
        "schema": SCHEMA_VERSION,
        "run": run,
        "vendor_calls": vendor_calls,
    })

    events = list(run.get("events") or [])
    event_counts = Counter(event.get("type") for event in events)
    stats = _last_stats(events)
    selected_vendors = [call for call in vendor_calls if call.get("selected")]
    lines = [
        "# TradingAgents 工程循环执行复盘", "",
        "## 基准运行", "",
        "| 字段 | 值 |", "|---|---|",
        f"| Run ID | `{run_id}` |",
        f"| Ticker | `{run.get('ticker')}` |",
        f"| Analysis date | `{run.get('analysis_date')}` |",
        f"| Run status | `{run.get('status')}` |",
        f"| Decision status | `{run.get('decision_status')}` |",
        f"| Events | `{len(events)}` |",
        f"| Vendor attempts | `{len(vendor_calls)}` |",
        "", "## 执行证据摘要", "",
        f"- Event types: `{dict(event_counts)}`",
        f"- Final stats: `{stats}`",
        f"- Selected vendors: `{[(c.get('method'), c.get('vendor'), c.get('call_id')) for c in selected_vendors]}`",
        "", "## 全流程人工 Review 清单", "",
        "- [ ] 逐 Agent 检查输入证据、工具调用、输出和交接是否一致。",
        "- [ ] 检查每个事实是否能追溯到 vendor call/source_id。",
        "- [ ] 检查 fallback 是否由 router 触发且通过相同 validator。",
        "- [ ] 检查交易数字是否全部来自可信 snapshot + 服务端风险政策。",
        "- [ ] 检查 NO_DECISION/失败是否被错误包装成 Hold/completed。",
        "- [ ] 检查 token、重复上下文、延迟和重复事件等 P1 成本问题。",
        "", "## Findings", "",
        "结构化 finding 以 `findings.json` 为准。人工新增 finding 时必须包含：",
        "`id/severity/title/evidence/root_cause/proposed_solution/acceptance/status`。",
    ]
    review_path = directory / "execution-review.md"
    review_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    build_p0_plan(run_id, root=root)
    cycle_path = directory / "cycle.json"
    manifest = json.loads(cycle_path.read_text(encoding="utf-8")) if cycle_path.exists() else {
        "schema": SCHEMA_VERSION, "run_id": run_id, "created_at": _now()
    }
    run_started = next(
        (event.get("content") or {} for event in events if event.get("type") == "run_started"),
        {},
    )
    selected_analysts = run.get("selected_analysts")
    if isinstance(selected_analysts, str):
        try:
            selected_analysts = json.loads(selected_analysts)
        except json.JSONDecodeError:
            selected_analysts = [
                item.strip() for item in selected_analysts.split(",") if item.strip()
            ]
    manifest.setdefault("request", {
        "ticker": run.get("ticker"),
        "analysis_date": run.get("analysis_date"),
        "analysis_mode": run_started.get("analysis_mode", "live"),
        "information_cutoff": (
            None
            if run_started.get("information_cutoff") == "live_at_call_time"
            else run_started.get("information_cutoff")
        ),
        "selected_analysts": list(selected_analysts or ()),
        "research_depth": int(run.get("research_depth") or 1),
    })
    manifest.update({"phase": "reviewed", "reviewed_at": _now()})
    _write_json(cycle_path, manifest)
    return review_path


def canonical_review_store() -> RunHistoryStore:
    """Open the server-owned history universe for reviewing scheduled/Web runs."""
    configured = os.environ.get("TRADINGAGENTS_CANONICAL_DB")
    path = (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".tradingagents" / "runs.db"
    )
    if path.resolve() == ENGINEERING_DB.resolve():
        raise ValueError("canonical review database cannot be the engineering database")
    return RunHistoryStore(path)


def build_p0_plan(run_id: str, *, root: Path = DEFAULT_ROOT) -> Path:
    directory = cycle_dir(run_id, root)
    payload = json.loads((directory / "findings.json").read_text(encoding="utf-8"))
    p0s = [item for item in payload.get("findings", []) if item.get("severity") == "P0"]
    lines = ["# P0 优化方案", "", f"Run ID: `{run_id}`", ""]
    if not p0s:
        lines.append("本次自动审计未发现 P0；仍需完成 execution-review.md 的人工检查。")
    for item in p0s:
        lines.extend([
            f"## {item['id']} — {item['title']}", "",
            f"- Evidence: {item['evidence']}",
            f"- Root cause: {item['root_cause']}",
            f"- Proposed solution: {item['proposed_solution']}",
            f"- Acceptance: {item['acceptance']}",
            "- Required tests: 单元测试 + 相关集成测试 + 同输入 NVDA 重跑。",
            "- Rollback: 保留旧行为的明确恢复点，但不得恢复 P0 绕过路径。",
            "",
        ])
    path = directory / "p0-plan.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def resolve_finding(
    run_id: str,
    finding_id: str,
    *,
    implementation_evidence: str,
    verification: str,
    root: Path = DEFAULT_ROOT,
) -> None:
    directory = cycle_dir(run_id, root)
    path = directory / "findings.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    for item in payload.get("findings", []):
        if item.get("id") == finding_id:
            if not implementation_evidence.strip() or not verification.strip():
                raise ValueError("resolved finding requires implementation and verification evidence")
            item.update({
                "status": P0_RESOLVED,
                "implementation_evidence": implementation_evidence.strip(),
                "verification": verification.strip(),
                "resolved_at": _now(),
            })
            _write_json(path, payload)
            build_p0_plan(run_id, root=root)
            return
    raise ValueError(f"finding not found: {finding_id}")


def plan_finding(
    run_id: str,
    finding_id: str,
    *,
    root_cause: str,
    proposed_solution: str,
    acceptance: str,
    root: Path = DEFAULT_ROOT,
) -> None:
    """Record the engineering analysis required before a finding can be resolved."""
    values = (root_cause.strip(), proposed_solution.strip(), acceptance.strip())
    if any(len(value) < 10 for value in values):
        raise ValueError("finding plan requires substantive root cause, solution, and acceptance")
    directory = cycle_dir(run_id, root)
    path = directory / "findings.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    for item in payload.get("findings", []):
        if item.get("id") == finding_id:
            item.update({
                "root_cause": values[0],
                "proposed_solution": values[1],
                "acceptance": values[2],
                "planned_at": _now(),
            })
            _write_json(path, payload)
            build_p0_plan(run_id, root=root)
            return
    raise ValueError(f"finding not found: {finding_id}")


def acknowledge_review(
    run_id: str, *, summary: str, reviewer: str, root: Path = DEFAULT_ROOT
) -> None:
    """Record that a human/engineering agent reviewed the whole execution trace."""
    if len(summary.strip()) < 20:
        raise ValueError("review acknowledgement requires a substantive summary")
    directory = cycle_dir(run_id, root)
    path = directory / "findings.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["review_acknowledgement"] = {
        "reviewer": reviewer.strip() or "unspecified",
        "summary": summary.strip(),
        "acknowledged_at": _now(),
    }
    _write_json(path, payload)


VERIFICATION_COMMANDS = (
    (sys.executable, "-m", "compileall", "-q", "tradingagents", "web/backend", "cli"),
    ("node", "--check", "web/frontend/app.js"),
    (
        sys.executable, "-m", "pytest", "-q",
        "tests/test_runtime_analysis_runner.py",
        "tests/test_web_backend.py::test_create_run_and_get_status",
        "tests/test_web_backend.py::test_run_create_request_uses_webui_defaults",
        "tests/test_web_backend.py::test_get_config_defaults_matches_webui_defaults",
        "tests/test_web_backend.py::test_get_analyst_prompts_exposes_prompt_catalog",
        "tests/test_web_backend.py::test_get_env_status_reports_provider_key_presence",
        "tests/test_web_backend.py::test_run_create_request_passes_webui_config",
        "tests/test_web_backend.py::test_run_request_rejects_arbitrary_backend_and_filesystem_paths",
        "tests/test_web_backend.py::test_run_request_rejects_hidden_config_overrides",
        "tests/test_api_key_env.py",
        "tests/test_cli_env_skip.py",
        "tests/test_trade_plan_validation.py",
        "tests/test_news_analyst_citation_retry.py",
        "tests/test_evidence_models.py",
        "tests/test_engineering_cycle.py",
    ),
    ("git", "diff", "--check"),
)


def verify_cycle(run_id: str, *, root: Path = DEFAULT_ROOT, repo: Path | None = None) -> Path:
    directory = cycle_dir(run_id, root)
    repo = repo or Path.cwd()
    results = []
    for command in VERIFICATION_COMMANDS:
        completed = subprocess.run(
            command, cwd=repo, text=True, capture_output=True, check=False
        )
        results.append({
            "command": list(command),
            "exit_code": completed.returncode,
            "stdout_tail": completed.stdout[-4000:],
            "stderr_tail": completed.stderr[-4000:],
        })
        if completed.returncode != 0:
            break
    payload = {
        "schema": SCHEMA_VERSION,
        "run_id": run_id,
        "verified_at": _now(),
        "passed": all(item["exit_code"] == 0 for item in results)
        and len(results) == len(VERIFICATION_COMMANDS),
        "results": results,
    }
    path = directory / "verification.json"
    _write_json(path, payload)
    return path


def gate_cycle(run_id: str, *, root: Path = DEFAULT_ROOT) -> Path:
    """Close only after every P0 has evidence and post-change verification passed."""
    directory = cycle_dir(run_id, root)
    findings = json.loads((directory / "findings.json").read_text(encoding="utf-8"))
    open_p0 = [
        item for item in findings.get("findings", [])
        if item.get("severity") == "P0" and item.get("status") != P0_RESOLVED
    ]
    incomplete = [
        item for item in findings.get("findings", [])
        if item.get("severity") == "P0" and (
            not item.get("implementation_evidence") or not item.get("verification")
        )
    ]
    unplanned = [
        item for item in findings.get("findings", [])
        if item.get("severity") == "P0" and (
            item.get("root_cause") == "待工程复盘确认"
            or len(str(item.get("root_cause") or "").strip()) < 10
            or len(str(item.get("proposed_solution") or "").strip()) < 10
            or len(str(item.get("acceptance") or "").strip()) < 10
        )
    ]
    verification_path = directory / "verification.json"
    verification = (
        json.loads(verification_path.read_text(encoding="utf-8"))
        if verification_path.exists() else {}
    )
    if open_p0 or incomplete or unplanned:
        ids = sorted({item["id"] for item in open_p0 + incomplete + unplanned})
        raise RuntimeError("P0 gate blocked by unresolved/incomplete/unplanned findings: " + ", ".join(ids))
    if not verification.get("passed"):
        raise RuntimeError("P0 gate requires a passing post-change verification run")
    acknowledgement = findings.get("review_acknowledgement") or {}
    if not acknowledgement.get("summary"):
        raise RuntimeError("P0 gate requires acknowledgement of the full execution review")
    resolved_times = [
        item.get("resolved_at", "") for item in findings.get("findings", [])
        if item.get("severity") == "P0"
    ]
    if resolved_times and verification.get("verified_at", "") < max(resolved_times):
        raise RuntimeError("verification must run after the latest P0 resolution")
    completion = {
        "schema": SCHEMA_VERSION,
        "run_id": run_id,
        "phase": "complete",
        "completed_at": _now(),
        "p0_findings": [
            item["id"] for item in findings.get("findings", [])
            if item.get("severity") == "P0"
        ],
        "verification": str(verification_path),
    }
    path = directory / "completion.json"
    _write_json(path, completion)
    cycle_path = directory / "cycle.json"
    manifest = json.loads(cycle_path.read_text(encoding="utf-8")) if cycle_path.exists() else {}
    manifest.update({"phase": "complete", "completed_at": completion["completed_at"]})
    _write_json(cycle_path, manifest)
    return path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run an audited NVDA baseline")
    run.add_argument("--symbol", default="NVDA")
    run.add_argument("--date")
    run.add_argument("--depth", type=int, choices=(1, 3, 5), default=1)
    rerun = commands.add_parser("rerun", help="rerun the exact baseline for P0 verification")
    rerun.add_argument("parent_run_id")
    review = commands.add_parser("review", help="export and review a terminal run")
    review.add_argument("run_id")
    review.add_argument(
        "--canonical",
        action="store_true",
        help="read the run from the server-owned CLI/Web/timer history database",
    )
    plan = commands.add_parser("plan", help="record P0 root cause and acceptance plan")
    plan.add_argument("run_id")
    plan.add_argument("finding_id")
    plan.add_argument("--root-cause", required=True)
    plan.add_argument("--solution", required=True)
    plan.add_argument("--acceptance", required=True)
    resolve = commands.add_parser("resolve", help="record P0 implementation evidence")
    resolve.add_argument("run_id")
    resolve.add_argument("finding_id")
    resolve.add_argument("--implementation", required=True)
    resolve.add_argument("--verification", required=True)
    acknowledge = commands.add_parser(
        "ack-review", help="acknowledge full execution review completion"
    )
    acknowledge.add_argument("run_id")
    acknowledge.add_argument("--reviewer", default="engineering-agent")
    acknowledge.add_argument("--summary", required=True)
    verify = commands.add_parser("verify", help="run the fixed post-change acceptance suite")
    verify.add_argument("run_id")
    gate = commands.add_parser("gate", help="close a cycle only when every P0 is resolved")
    gate.add_argument("run_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "run":
        print(run_baseline(
            symbol=args.symbol, analysis_date=args.date,
            research_depth=args.depth, root=args.root,
        ))
    elif args.command == "rerun":
        print(rerun_baseline(args.parent_run_id, root=args.root))
    elif args.command == "review":
        store = canonical_review_store() if args.canonical else history_store
        print(build_review(args.run_id, root=args.root, store=store))
    elif args.command == "plan":
        plan_finding(
            args.run_id, args.finding_id,
            root_cause=args.root_cause,
            proposed_solution=args.solution,
            acceptance=args.acceptance,
            root=args.root,
        )
    elif args.command == "resolve":
        resolve_finding(
            args.run_id, args.finding_id,
            implementation_evidence=args.implementation,
            verification=args.verification,
            root=args.root,
        )
    elif args.command == "ack-review":
        acknowledge_review(
            args.run_id, summary=args.summary,
            reviewer=args.reviewer, root=args.root,
        )
    elif args.command == "verify":
        print(verify_cycle(args.run_id, root=args.root))
    elif args.command == "gate":
        print(gate_cycle(args.run_id, root=args.root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
