from tradingagents.runtime import AnalysisRequest, run_analysis_once


result = run_analysis_once(
    AnalysisRequest(ticker="NVDA", analysis_date="2024-05-10", debug=True)
)
print(result.decision if result.decision is not None else "NO_DECISION")
