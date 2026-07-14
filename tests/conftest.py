"""Shared pytest fixtures that prevent CI hangs when API keys are absent."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# Set a process-unique database before pytest imports any test modules.  This is
# the first line of defence against collection-time imports initializing the
# runtime store against a developer's real history database.  Each test gets a
# separate database in ``_isolate_run_storage`` below.
_PYTEST_DB_DIR = tempfile.TemporaryDirectory(prefix="tradingagents-pytest-")
_PYTEST_BOOTSTRAP_DB = Path(_PYTEST_DB_DIR.name) / "bootstrap-runs.db"
os.environ["TRADINGAGENTS_DB"] = str(_PYTEST_BOOTSTRAP_DB)


def pytest_configure(config):
    for marker in ("unit", "integration", "smoke"):
        config.addinivalue_line("markers", f"{marker}: {marker}-level tests")


_API_KEY_ENV_VARS = (
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_CN_API_KEY",
    "ZHIPU_API_KEY",
    "ZHIPU_CN_API_KEY",
    "MINIMAX_API_KEY",
    "MINIMAX_CN_API_KEY",
    "OPENROUTER_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
)


@pytest.fixture(autouse=True)
def _dummy_api_keys(monkeypatch):
    for env_var in _API_KEY_ENV_VARS:
        # `or` not a .get default: an env var present but empty (e.g. a key left
        # blank in a .env copied from .env.example) must still get the placeholder.
        monkeypatch.setenv(env_var, os.environ.get(env_var) or "placeholder")


@pytest.fixture(autouse=True)
def _isolate_run_storage(monkeypatch, tmp_path):
    """Give every test one SQLite database shared by runtime and Web stores."""
    from tradingagents import runtime as runtime_module
    from tradingagents.runtime import history as history_module
    from tradingagents.runtime.history import RunHistoryStore
    from tradingagents.dataflows import vendor_verification as verification_module
    from tradingagents.dataflows.vendor_verification import VendorVerificationStore
    from web.backend import task_store as task_store_module

    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("TRADINGAGENTS_DB", str(db_path))

    runtime_store = RunHistoryStore(db_path)
    vendor_store = VendorVerificationStore(db_path)
    monkeypatch.setattr(history_module, "history_store", runtime_store)
    monkeypatch.setattr(runtime_module, "history_store", runtime_store)
    monkeypatch.setattr(
        verification_module, "vendor_verification_store", vendor_store
    )

    # task_store imports the singleton by value, so patch that alias as well as
    # its module-level Web store.  Both stores must point at the same test DB.
    monkeypatch.setattr(task_store_module, "history_store", runtime_store)
    web_store = task_store_module.TaskStore(db_path)
    monkeypatch.setattr(task_store_module, "store", web_store)

    # These modules also import store singletons by value.  Patch them only if
    # they were already loaded; modules imported later will see patched values.
    main_module = sys.modules.get("web.backend.main")
    if main_module is not None:
        monkeypatch.setattr(main_module, "store", web_store)
        monkeypatch.setattr(
            main_module, "vendor_verification_store", vendor_store
        )
    engineering_module = sys.modules.get("tradingagents.engineering_cycle")
    if engineering_module is not None:
        monkeypatch.setattr(engineering_module, "history_store", runtime_store)

    yield db_path


@pytest.fixture(autouse=True)
def _isolate_config():
    """Reset the global dataflows config before and after each test.

    ``set_config`` merges (it never clears keys absent from the override), so a
    test that sets e.g. ``tool_vendors`` would otherwise leak into later tests
    and make routing behavior order-dependent. Replace the global outright so
    every test starts from a clean DEFAULT_CONFIG.
    """
    import copy

    import tradingagents.dataflows.config as config_module
    import tradingagents.default_config as default_config

    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    yield
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


@pytest.fixture()
def mock_llm_client():
    client = MagicMock()
    client.get_llm.return_value = MagicMock()
    with patch(
        "tradingagents.llm_clients.factory.create_llm_client",
        return_value=client,
    ):
        yield client
