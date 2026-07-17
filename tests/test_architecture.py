import json

from tradingagents import architecture


def test_implementation_digest_is_path_independent_and_content_sensitive(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    for root in (first, second):
        (root / "agents").mkdir(parents=True)
        (root / "automation").mkdir(parents=True)
        (root / "agents" / "prompt.py").write_text("PROMPT = 'one'\n", encoding="utf-8")
        (root / "automation" / "daily.py").write_text(
            "OPERATIONAL = 'one'\n", encoding="utf-8"
        )
        (root / "ignored.txt").write_text("not executable\n", encoding="utf-8")

    first_digest = architecture.architecture_implementation_digest(first)
    (second / "ignored.txt").write_text("different docs\n", encoding="utf-8")
    second_digest = architecture.architecture_implementation_digest(second)
    assert first_digest == second_digest

    (second / "automation" / "daily.py").write_text(
        "OPERATIONAL = 'two'\n", encoding="utf-8"
    )
    assert architecture.architecture_implementation_digest(second) == first_digest

    (second / "agents" / "prompt.py").write_text("PROMPT = 'two'\n", encoding="utf-8")
    assert architecture.architecture_implementation_digest(second) != first_digest


def test_manifest_fingerprint_changes_with_effective_implementation(monkeypatch):
    def manifest():
        return architecture.build_architecture_manifest(
            version="candidate",
            selected_analysts=("market", "news"),
            research_depth=1,
            llm_provider="minimax-cn",
            quick_think_llm="MiniMax-M3",
            deep_think_llm="MiniMax-M3",
        )

    monkeypatch.setattr(
        architecture,
        "architecture_implementation_digest",
        lambda: "a" * 64,
    )
    first = manifest()
    monkeypatch.setattr(
        architecture,
        "architecture_implementation_digest",
        lambda: "b" * 64,
    )
    second = manifest()

    assert first["schema"] == "tradingagents/agent-architecture-manifest/v3"
    assert "tradingagents/agents/**/*.py" in first["implementation_digest_scope"]
    assert "tradingagents/automation/**/*.py" not in first["implementation_digest_scope"]
    assert architecture.architecture_fingerprint(first) != architecture.architecture_fingerprint(
        second
    )


def test_manifest_captures_only_safe_decision_affecting_config(monkeypatch):
    monkeypatch.setattr(
        architecture,
        "architecture_implementation_digest",
        lambda: "a" * 64,
    )
    common = {
        "version": "candidate",
        "selected_analysts": ("market",),
        "research_depth": 1,
        "llm_provider": "minimax-cn",
        "quick_think_llm": "MiniMax-M3",
        "deep_think_llm": "MiniMax-M3",
    }
    first = architecture.build_architecture_manifest(
        **common,
        effective_config={
            "output_language": "Chinese",
            "max_debate_rounds": 1,
            "max_risk_discuss_rounds": 1,
            "data_vendors": {"news_data": "longbridge_mcp, longbridge"},
            "trade_risk_policy": {"max_position_pct": 5.0},
            "backend_url": "https://user:credential@example.invalid/v1",
            "OPENAI_API_KEY": "must-not-persist",
        },
    )
    second = architecture.build_architecture_manifest(
        **common,
        effective_config={
            **first["decision_config"],
            "output_language": "English",
        },
    )

    serialized = json.dumps(first, sort_keys=True)
    assert "must-not-persist" not in serialized
    assert "credential" not in serialized
    assert first["decision_config"]["custom_backend_configured"] is True
    assert first["decision_config"]["data_vendors"] == {
        "news_data": "longbridge_mcp, longbridge"
    }
    assert architecture.architecture_fingerprint(first) != architecture.architecture_fingerprint(
        second
    )


def test_experiment_input_identity_excludes_treatment_and_binds_upstream_state():
    state = {
        "company_of_interest": "NVDA",
        "trade_date": "2026-07-17",
        "asset_type": "stock",
        "instrument_context": {"exchange": "NASDAQ", "currency": "USD"},
        "investment_debate_state": {"history": "Bull: growth\nBear: valuation"},
        "past_context": "baseline context",
        "longitudinal_context_mode": "portfolio_only",
    }
    baseline = architecture.architecture_experiment_input_identity(state)
    challenger = architecture.architecture_experiment_input_identity({
        **state,
        "past_context": "challenger context",
        "longitudinal_context_mode": "research_and_portfolio",
    })
    changed_upstream = architecture.architecture_experiment_input_identity({
        **state,
        "investment_debate_state": {"history": "Different debate"},
    })

    assert baseline["schema"] == (
        "tradingagents/research-manager-pre-context-input/v1"
    )
    assert baseline["complete"] is True
    assert baseline["fingerprint"] == challenger["fingerprint"]
    assert baseline["fingerprint"] != changed_upstream["fingerprint"]


def test_experiment_input_identity_marks_missing_branch_inputs_incomplete():
    identity = architecture.architecture_experiment_input_identity({
        "company_of_interest": "NVDA",
        "trade_date": "2026-07-17",
    })
    assert identity["complete"] is False
    assert len(identity["fingerprint"]) == 64

    unsupported = architecture.architecture_experiment_input_identity({
        "company_of_interest": "NVDA",
        "trade_date": "2026-07-17",
        "instrument_context": {"unsupported": object()},
        "investment_debate_state": {"history": "Debate"},
    })
    assert unsupported["complete"] is False
