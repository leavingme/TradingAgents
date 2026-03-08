import os

DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", "./results"),
    "data_cache_dir": os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
        "dataflows/data_cache",
    ),
    # LLM settings
    "llm_provider": "custom",
    "deep_think_llm": os.getenv("CUSTOM_DEEP_MODEL", "kimi-code"),
    "quick_think_llm": os.getenv("CUSTOM_QUICK_MODEL", "kimi-code"),
    "backend_url": os.getenv("OPENAI_API_BASE", "http://127.0.0.1:4000/v1"),
    "llm_timeout": 120,              # 单次 LLM 调用超时秒数（默认 120s）
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 250,
    # Data vendor configuration
    # Category-level configuration (default for all tools in category)
    "data_vendors": {
        "core_stock_apis": "longbridge",       # 股价 K 线：长桥
        "technical_indicators": "longbridge",  # 技术指标：长桥
        "fundamental_data": "alpha_vantage",   # 基本面：Alpha Vantage（yfinance 在国内不稳定）
        "news_data": "alpha_vantage, web_search, duckduckgo", # 新闻优先级：Alpha 第一, Kimi 第二, DDG 第三
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
}
