from datetime import date
import json
from pathlib import Path

import pytest

from tradingagents.engineering_cycle import (
    acknowledge_review,
    build_review,
    cycle_dir,
    default_analysis_date,
    gate_cycle,
    plan_finding,
    resolve_finding,
    verify_cycle,
)


class FakeStore:
    def __init__(self, run, calls):
        self.run = run
        self.calls = calls

    def get_run(self, run_id):
        return self.run if run_id == self.run["run_id"] else None

    def get_vendor_calls(self, run_id):
        return self.calls


def _run(*, status="completed", decision_status="validated"):
    return {
        "run_id": "NVDA-cycle-test",
        "ticker": "NVDA",
        "analysis_date": "2026-07-10",
        "status": status,
        "decision_status": decision_status,
        "events": [
            {
                "type": "stats",
                "content": {"llm_calls": 10, "tool_calls": 12, "tokens_in": 1000},
            },
            {
                "type": "run_completed",
                "content": {"decision_status": decision_status},
            },
        ],
    }


def _calls():
    return [{
        "call_id": "call-1", "attempt": 1, "selected": 1,
        "method": "get_stock_data", "vendor": "longbridge_mcp",
        "result_hash": "abc123",
    }]


@pytest.mark.unit
def test_default_date_never_uses_forming_or_weekend_bar():
    assert default_analysis_date(date(2026, 7, 13)) == "2026-07-10"  # Monday
    assert default_analysis_date(date(2026, 7, 14)) == "2026-07-13"  # Tuesday


@pytest.mark.unit
def test_cycle_dir_rejects_path_traversal(tmp_path):
    with pytest.raises(ValueError, match="unsafe"):
        cycle_dir("../../escape", tmp_path)


@pytest.mark.unit
def test_review_exports_evidence_and_p0_plan(tmp_path):
    store = FakeStore(_run(), _calls())
    review = build_review("NVDA-cycle-test", root=tmp_path, store=store)
    directory = review.parent
    assert review.exists()
    assert (directory / "execution-evidence.json").exists()
    assert (directory / "p0-plan.md").exists()
    findings = json.loads((directory / "findings.json").read_text(encoding="utf-8"))
    assert findings["findings"] == []


@pytest.mark.unit
def test_review_detects_executable_numbers_in_validated_underweight(tmp_path):
    run = _run()
    run["events"][-1]["content"]["decision"] = (
        "**Rating**: Underweight\n\n跌破201美元减仓至25%。"
    )
    store = FakeStore(run, _calls())
    build_review("NVDA-cycle-test", root=tmp_path, store=store)
    payload = json.loads(
        (tmp_path / "NVDA-cycle-test" / "findings.json").read_text(encoding="utf-8")
    )
    assert "P0-NONLONG-EXECUTABLE-NUMBERS" in {
        item["id"] for item in payload["findings"]
    }

    run["events"][-1]["content"]["decision"] = "**Rating**: Underweight\n\n等待确认。"
    build_review("NVDA-cycle-test", root=tmp_path, store=store)
    refreshed = json.loads(
        (tmp_path / "NVDA-cycle-test" / "findings.json").read_text(encoding="utf-8")
    )
    assert "P0-NONLONG-EXECUTABLE-NUMBERS" not in {
        item["id"] for item in refreshed["findings"]
    }


@pytest.mark.unit
def test_failed_run_creates_p0_and_gate_requires_resolution_review_and_verification(
    tmp_path, monkeypatch
):
    from tradingagents import engineering_cycle as module

    store = FakeStore(
        {
            **_run(status="failed", decision_status="unavailable"),
            "events": [{"type": "error", "content": {"error": "boom"}}],
        },
        [],
    )
    build_review("NVDA-cycle-test", root=tmp_path, store=store)
    with pytest.raises(RuntimeError, match="P0 gate blocked"):
        gate_cycle("NVDA-cycle-test", root=tmp_path)

    findings_path = tmp_path / "NVDA-cycle-test" / "findings.json"
    payload = json.loads(findings_path.read_text(encoding="utf-8"))
    p0_ids = [item["id"] for item in payload["findings"] if item["severity"] == "P0"]
    assert set(p0_ids) == {
        "P0-RUN-FAILURE", "P0-NO-VALID-DECISION", "P0-MISSING-VENDOR-AUDIT"
    }
    for finding_id in p0_ids:
        plan_finding(
            "NVDA-cycle-test", finding_id,
            root_cause=f"明确定位 {finding_id} 的确定性根因与影响边界",
            proposed_solution=f"在统一运行边界修复 {finding_id} 并保留类型化失败",
            acceptance=f"相同输入重跑并由测试证明 {finding_id} 不再出现",
            root=tmp_path,
        )
        resolve_finding(
            "NVDA-cycle-test", finding_id,
            implementation_evidence=f"commit fixes {finding_id}",
            verification=f"test covers {finding_id}",
            root=tmp_path,
        )
    acknowledge_review(
        "NVDA-cycle-test",
        reviewer="tester",
        summary="逐 Agent、vendor、决策状态和交易门禁完成了完整执行复盘。",
        root=tmp_path,
    )
    monkeypatch.setattr(
        module,
        "VERIFICATION_COMMANDS",
        ((module.sys.executable, "-c", "print('ok')"),),
    )
    verify_cycle("NVDA-cycle-test", root=tmp_path, repo=Path.cwd())
    completion = gate_cycle("NVDA-cycle-test", root=tmp_path)
    assert json.loads(completion.read_text(encoding="utf-8"))["phase"] == "complete"


@pytest.mark.unit
def test_gate_rejects_verification_older_than_p0_resolution(tmp_path):
    store = FakeStore(_run(decision_status="unavailable"), _calls())
    build_review("NVDA-cycle-test", root=tmp_path, store=store)
    directory = tmp_path / "NVDA-cycle-test"
    acknowledge_review(
        "NVDA-cycle-test", reviewer="tester",
        summary="已检查整个执行过程并确认唯一 P0 的证据、根因和修复方案。",
        root=tmp_path,
    )
    (directory / "verification.json").write_text(json.dumps({
        "passed": True, "verified_at": "2020-01-01T00:00:00+00:00"
    }), encoding="utf-8")
    plan_finding(
        "NVDA-cycle-test", "P0-NO-VALID-DECISION",
        root_cause="最终决策未能通过确定性的结构化交易数字验证门禁",
        proposed_solution="修复结构化输出并保持失败状态向运行层完整传播",
        acceptance="同输入重跑得到 validated 且相关单元测试全部通过",
        root=tmp_path,
    )
    resolve_finding(
        "NVDA-cycle-test", "P0-NO-VALID-DECISION",
        implementation_evidence="fixed", verification="covered",
        root=tmp_path,
    )
    with pytest.raises(RuntimeError, match="after the latest P0 resolution"):
        gate_cycle("NVDA-cycle-test", root=tmp_path)
