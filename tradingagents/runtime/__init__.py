"""Headless analysis runtime shared by CLI, APIs, and future UIs."""

from .analysis_runner import run_analysis_once, run_analysis_stream
from .events import AnalysisEvent, AnalysisRequest, AnalysisResult
from .stats_handler import StatsCallbackHandler
from .history import history_store, RunHistoryStore, DB_PATH

__all__ = [
    "AnalysisEvent",
    "AnalysisRequest",
    "AnalysisResult",
    "StatsCallbackHandler",
    "run_analysis_once",
    "run_analysis_stream",
    "history_store",
    "RunHistoryStore",
    "DB_PATH",
]
