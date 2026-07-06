import types

from typer.testing import CliRunner

import cli.main as m


def test_web_command_starts_uvicorn(monkeypatch):
    calls = []

    fake_uvicorn = types.SimpleNamespace(
        run=lambda app, **kwargs: calls.append((app, kwargs))
    )
    monkeypatch.setitem(__import__("sys").modules, "uvicorn", fake_uvicorn)

    result = CliRunner().invoke(
        m.app,
        ["web", "--host", "0.0.0.0", "--port", "9999", "--reload"],
    )

    assert result.exit_code == 0
    assert calls == [
        (
            "web.backend.main:app",
            {"host": "0.0.0.0", "port": 9999, "reload": True},
        )
    ]
