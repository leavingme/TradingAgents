from tradingagents.runtime.events import AnalysisEvent
from tradingagents.runtime.report_throttle import ReportSectionThrottler


def _section(version: int, *, run_id: str = "run-1", section: str = "debate"):
    return AnalysisEvent(
        type="report_section",
        run_id=run_id,
        agent="Researcher",
        content={"section": section, "text": f"version-{version}"},
    )


def test_report_section_throttle_keeps_leading_and_latest_trailing_version():
    now = [10.0]
    throttle = ReportSectionThrottler(0.5, clock=lambda: now[0])

    emitted = list(throttle.push(_section(0)))
    for version in range(1, 100):
        emitted.extend(throttle.push(_section(version)))
    terminal = AnalysisEvent(type="run_completed", run_id="run-1", content={})
    emitted.extend(throttle.push(terminal))

    reports = [event for event in emitted if event.type == "report_section"]
    assert len(reports) == 2
    assert reports[0].content["text"] == "version-0"
    assert reports[-1].content["text"] == "version-99"
    assert emitted[-1].type == "run_completed"


def test_report_section_throttle_is_scoped_by_run_and_section():
    throttle = ReportSectionThrottler(10, clock=lambda: 1.0)

    emitted = []
    emitted.extend(throttle.push(_section(0, run_id="run-a", section="bull")))
    emitted.extend(throttle.push(_section(0, run_id="run-a", section="bear")))
    emitted.extend(throttle.push(_section(0, run_id="run-b", section="bull")))

    assert [(event.run_id, event.content["section"]) for event in emitted] == [
        ("run-a", "bull"),
        ("run-a", "bear"),
        ("run-b", "bull"),
    ]


def test_report_section_throttle_flushes_before_agent_completion():
    throttle = ReportSectionThrottler(10, clock=lambda: 1.0)
    list(throttle.push(_section(0)))
    assert list(throttle.push(_section(1))) == []

    completed = AnalysisEvent(
        type="agent_status",
        run_id="run-1",
        agent="Researcher",
        content={"status": "completed"},
    )
    emitted = list(throttle.push(completed))

    assert [event.type for event in emitted] == ["report_section", "agent_status"]
    assert emitted[0].content["text"] == "version-1"


def test_report_section_throttle_flushes_due_updates_without_terminal_event():
    now = [1.0]
    throttle = ReportSectionThrottler(0.5, clock=lambda: now[0])
    list(throttle.push(_section(0)))
    list(throttle.push(_section(1)))
    now[0] = 1.6

    message = AnalysisEvent(type="message", run_id="run-1", content={"text": "next"})
    emitted = list(throttle.push(message))

    assert [event.type for event in emitted] == ["report_section", "message"]
    assert emitted[0].content["text"] == "version-1"
