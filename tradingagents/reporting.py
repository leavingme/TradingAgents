"""Reusable report-tree writer shared by the CLI and the programmatic API.

Writes a run's per-section markdown (analysts, research, trading, risk,
portfolio) plus a consolidated ``complete_report.md`` under ``save_path``. The
CLI and ``TradingAgentsGraph.save_reports`` both call this, so a headless / API
run produces the same on-disk report tree a CLI run does.
"""

from datetime import datetime
from pathlib import Path

from tradingagents.dataflows.config import get_config


_AGENT_LABELS = {
    "en": {
        "Market Analyst": "Market Analyst",
        "Sentiment Analyst": "Sentiment Analyst",
        "News Analyst": "News Analyst",
        "Fundamentals Analyst": "Fundamentals Analyst",
        "Bull Researcher": "Bull Researcher",
        "Bear Researcher": "Bear Researcher",
        "Research Manager": "Research Manager",
        "Trader": "Trader",
        "Aggressive Analyst": "Aggressive Analyst",
        "Conservative Analyst": "Conservative Analyst",
        "Neutral Analyst": "Neutral Analyst",
        "Portfolio Manager": "Portfolio Manager",
    },
    "zh": {
        "Market Analyst": "市场分析师",
        "Sentiment Analyst": "情绪分析师",
        "News Analyst": "新闻分析师",
        "Fundamentals Analyst": "基本面分析师",
        "Bull Researcher": "看多研究员",
        "Bear Researcher": "看空研究员",
        "Research Manager": "研究经理",
        "Trader": "交易员",
        "Aggressive Analyst": "激进风险分析师",
        "Conservative Analyst": "保守风险分析师",
        "Neutral Analyst": "中性风险分析师",
        "Portfolio Manager": "组合经理",
    },
}

_SECTION_LABELS = {
    "complete_report": {
        "en": "Complete Analysis Report",
        "zh": "完整分析报告",
    },
    "report_header": {
        "en": "Trading Analysis Report: {ticker}",
        "zh": "{ticker} 交易分析报告",
    },
    "generated": {
        "en": "Generated",
        "zh": "生成时间",
    },
    "analyst_team": {
        "en": "I. Analyst Team Reports",
        "zh": "I. 分析师团队报告",
    },
    "research_team": {
        "en": "II. Research Team Decision",
        "zh": "II. 研究团队决策",
    },
    "trading_team": {
        "en": "III. Trading Team Plan",
        "zh": "III. 交易团队计划",
    },
    "risk_team": {
        "en": "IV. Risk Management Team Decision",
        "zh": "IV. 风险管理团队决策",
    },
    "portfolio_manager": {
        "en": "V. Portfolio Manager Decision",
        "zh": "V. 组合经理决策",
    },
}


def report_locale(output_language: str | None = None) -> str:
    """Return the display locale used for user-visible report labels."""
    language = output_language
    if language is None:
        language = get_config().get("output_language", "Chinese")
    normalized = str(language).strip().lower()
    if normalized in {"chinese", "中文", "zh", "zh-cn", "zh_cn", "cn"}:
        return "zh"
    return "en"


def report_agent_label(name: str, output_language: str | None = None) -> str:
    """Localize a canonical agent name for report display."""
    locale = report_locale(output_language)
    return _AGENT_LABELS.get(locale, {}).get(name) or _AGENT_LABELS["en"].get(name, name)


def report_section_label(section: str, output_language: str | None = None) -> str:
    """Localize a canonical report section label."""
    locale = report_locale(output_language)
    labels = _SECTION_LABELS.get(section, {})
    return labels.get(locale) or labels.get("en") or section


def write_report_tree(final_state: dict, ticker: str, save_path) -> Path:
    """Save a completed run's reports to ``save_path``; return the complete-report path."""
    save_path = Path(save_path)
    save_path.mkdir(parents=True, exist_ok=True)
    sections = []
    output_language = get_config().get("output_language", "Chinese")

    # 1. Analysts
    analysts_dir = save_path / "1_analysts"
    analyst_parts = []
    if final_state.get("market_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "market.md").write_text(final_state["market_report"], encoding="utf-8")
        analyst_parts.append(("Market Analyst", final_state["market_report"]))
    if final_state.get("sentiment_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "sentiment.md").write_text(final_state["sentiment_report"], encoding="utf-8")
        analyst_parts.append(("Sentiment Analyst", final_state["sentiment_report"]))
    if final_state.get("news_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "news.md").write_text(final_state["news_report"], encoding="utf-8")
        analyst_parts.append(("News Analyst", final_state["news_report"]))
    if final_state.get("fundamentals_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "fundamentals.md").write_text(final_state["fundamentals_report"], encoding="utf-8")
        analyst_parts.append(("Fundamentals Analyst", final_state["fundamentals_report"]))
    if analyst_parts:
        content = "\n\n".join(
            f"### {report_agent_label(name, output_language)}\n{text}" for name, text in analyst_parts
        )
        sections.append(f"## {report_section_label('analyst_team', output_language)}\n\n{content}")

    # 2. Research
    if final_state.get("investment_debate_state"):
        research_dir = save_path / "2_research"
        debate = final_state["investment_debate_state"]
        research_parts = []
        if debate.get("bull_history"):
            research_dir.mkdir(exist_ok=True)
            (research_dir / "bull.md").write_text(debate["bull_history"], encoding="utf-8")
            research_parts.append(("Bull Researcher", debate["bull_history"]))
        if debate.get("bear_history"):
            research_dir.mkdir(exist_ok=True)
            (research_dir / "bear.md").write_text(debate["bear_history"], encoding="utf-8")
            research_parts.append(("Bear Researcher", debate["bear_history"]))
        if debate.get("judge_decision"):
            research_dir.mkdir(exist_ok=True)
            (research_dir / "manager.md").write_text(debate["judge_decision"], encoding="utf-8")
            research_parts.append(("Research Manager", debate["judge_decision"]))
        if research_parts:
            content = "\n\n".join(
                f"### {report_agent_label(name, output_language)}\n{text}" for name, text in research_parts
            )
            sections.append(f"## {report_section_label('research_team', output_language)}\n\n{content}")

    # 3. Trading
    if final_state.get("trader_investment_plan"):
        trading_dir = save_path / "3_trading"
        trading_dir.mkdir(exist_ok=True)
        (trading_dir / "trader.md").write_text(final_state["trader_investment_plan"], encoding="utf-8")
        sections.append(
            f"## {report_section_label('trading_team', output_language)}\n\n"
            f"### {report_agent_label('Trader', output_language)}\n{final_state['trader_investment_plan']}"
        )

    # 4. Risk Management
    if final_state.get("risk_debate_state"):
        risk_dir = save_path / "4_risk"
        risk = final_state["risk_debate_state"]
        risk_parts = []
        if risk.get("aggressive_history"):
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / "aggressive.md").write_text(risk["aggressive_history"], encoding="utf-8")
            risk_parts.append(("Aggressive Analyst", risk["aggressive_history"]))
        if risk.get("conservative_history"):
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / "conservative.md").write_text(risk["conservative_history"], encoding="utf-8")
            risk_parts.append(("Conservative Analyst", risk["conservative_history"]))
        if risk.get("neutral_history"):
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / "neutral.md").write_text(risk["neutral_history"], encoding="utf-8")
            risk_parts.append(("Neutral Analyst", risk["neutral_history"]))
        if risk_parts:
            content = "\n\n".join(
                f"### {report_agent_label(name, output_language)}\n{text}" for name, text in risk_parts
            )
            sections.append(f"## {report_section_label('risk_team', output_language)}\n\n{content}")

        # 5. Portfolio Manager
        if risk.get("judge_decision"):
            portfolio_dir = save_path / "5_portfolio"
            portfolio_dir.mkdir(exist_ok=True)
            (portfolio_dir / "decision.md").write_text(risk["judge_decision"], encoding="utf-8")
            sections.append(
                f"## {report_section_label('portfolio_manager', output_language)}\n\n"
                f"### {report_agent_label('Portfolio Manager', output_language)}\n{risk['judge_decision']}"
            )

    # Write consolidated report
    title = report_section_label("report_header", output_language).format(ticker=ticker)
    generated = report_section_label("generated", output_language)
    header = f"# {title}\n\n{generated}: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    (save_path / "complete_report.md").write_text(header + "\n\n".join(sections), encoding="utf-8")
    return save_path / "complete_report.md"
