"""Headless analysis runtime shared by CLI, APIs, and future UIs."""

from .analysis_runner import run_analysis_once, run_analysis_stream
from .events import (
    AnalysisEvent,
    AnalysisExecutionError,
    AnalysisRequest,
    AnalysisResult,
    OUTCOME_SETTLEMENT_RETRYABLE_ERROR_TYPES,
    runtime_error_status,
)
from .stats_handler import StatsCallbackHandler
from .history import history_store, RunHistoryStore, DB_PATH

__all__ = [
    "AnalysisEvent",
    "AnalysisExecutionError",
    "AnalysisRequest",
    "AnalysisResult",
    "OUTCOME_SETTLEMENT_RETRYABLE_ERROR_TYPES",
    "runtime_error_status",
    "StatsCallbackHandler",
    "run_analysis_once",
    "run_analysis_stream",
    "history_store",
    "RunHistoryStore",
    "DB_PATH",
]
