from web.backend.web_config_store import WebConfigStore
import asyncio
import json


def test_web_config_store_persists_runtime_and_provider_settings(tmp_path):
    path = tmp_path / "web_config.json"
    store = WebConfigStore(path)

    initial = store.load()
    assert initial["persisted"] is False
    assert [row["id"] for row in initial["providers"]["social_data"]] == ["bird", "reddit"]
    assert initial["providers"]["technical_indicators"][:3] == [
        {"id": "westock", "enabled": True},
        {"id": "longbridge_mcp", "enabled": True},
        {"id": "longbridge", "enabled": False},
    ]

    saved = store.save({
        "settings": {
            "output_language": "Japanese",
            "llm_provider": "minimax-cn",
            "ignored_secret": "must-not-persist",
        },
        "providers": {
            "social_data": [
                {"id": "reddit", "enabled": True},
                {"id": "bird", "enabled": False},
            ],
        },
    })

    assert saved["persisted"] is True
    assert saved["settings"] == {
        "output_language": "Japanese",
        "llm_provider": "minimax-cn",
    }
    assert saved["providers"]["social_data"] == [
        {"id": "reddit", "enabled": True},
        {"id": "bird", "enabled": False},
    ]
    assert WebConfigStore(path).load() == saved


def test_web_config_store_partial_save_preserves_other_section(tmp_path):
    store = WebConfigStore(tmp_path / "web_config.json")
    store.save({"settings": {"research_depth": 3}})
    updated = store.save({
        "providers": {"news_data": [{"id": "duckduckgo", "enabled": True}]}
    })

    assert updated["settings"]["research_depth"] == 3
    assert updated["providers"]["news_data"][0] == {
        "id": "duckduckgo",
        "enabled": True,
    }


def test_web_config_store_migrates_legacy_default_news_chain(tmp_path):
    path = tmp_path / "legacy-news.json"
    path.write_text(json.dumps({
        "settings": {},
        "providers": {
            "news_data": [
                {"id": "westock", "enabled": True},
                {"id": "duckduckgo", "enabled": True},
                {"id": "alpha_vantage", "enabled": True},
            ],
        },
    }))

    news = WebConfigStore(path).load()["providers"]["news_data"]

    assert [row["id"] for row in news[:2]] == ["longbridge_mcp", "longbridge"]
    assert all(row["enabled"] for row in news)


def test_web_config_store_migrates_legacy_default_indicator_chain(tmp_path):
    path = tmp_path / "legacy-indicators.json"
    path.write_text(json.dumps({
        "settings": {},
        "providers": {
            "technical_indicators": [
                {"id": "longbridge_mcp", "enabled": True},
                {"id": "longbridge", "enabled": True},
                {"id": "westock", "enabled": True},
                {"id": "alpha_vantage", "enabled": False},
            ],
        },
    }))

    indicators = WebConfigStore(path).load()["providers"]["technical_indicators"]

    assert indicators[:2] == [
        {"id": "westock", "enabled": True},
        {"id": "longbridge_mcp", "enabled": True},
    ]
    assert {row["id"]: row["enabled"] for row in indicators}["longbridge"] is False


def test_web_config_api_round_trip(monkeypatch, tmp_path):
    from web.backend import main

    store = WebConfigStore(tmp_path / "api-web-config.json")
    monkeypatch.setattr(main, "web_config_store", store)

    assert asyncio.run(main.get_web_config())["persisted"] is False
    saved = asyncio.run(main.update_web_config({
        "settings": {"output_language": "Chinese"},
    }))
    assert saved["persisted"] is True
    assert asyncio.run(main.get_web_config())["settings"]["output_language"] == "Chinese"
    assert asyncio.run(main.reset_web_config())["persisted"] is False
