import types

from typer.testing import CliRunner

import cli.main as m


def test_web_command_starts_uvicorn(monkeypatch):
    calls = []

    fake_uvicorn = types.SimpleNamespace(
        run=lambda app, **kwargs: calls.append((app, kwargs))
    )
    monkeypatch.setitem(__import__("sys").modules, "uvicorn", fake_uvicorn)
    monkeypatch.setenv("TRADINGAGENTS_WEB_AUTH_TOKEN", "test-secret")

    result = CliRunner().invoke(
        m.app,
        ["web", "--host", "0.0.0.0", "--port", "9999", "--reload"],
    )

    assert result.exit_code == 0
    assert calls == [
        (
            "web.backend.main:app",
            {
                "host": "0.0.0.0",
                "port": 9999,
                "reload": True,
                "reload_dirs": [
                    str(m.Path(m.__file__).resolve().parents[1] / directory)
                    for directory in ("cli", "tradingagents", "web")
                ],
                "app_dir": str(m.Path(m.__file__).resolve().parents[1]),
            },
        )
    ]


def test_non_loopback_web_requires_auth_token(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_WEB_AUTH_TOKEN", raising=False)
    result = CliRunner().invoke(m.app, ["web", "--host", "0.0.0.0"])
    assert result.exit_code == 2
