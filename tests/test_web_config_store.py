from web.backend.web_config_store import WebConfigStore
import asyncio


def test_web_config_store_persists_runtime_and_provider_settings(tmp_path):
    path = tmp_path / "web_config.json"
    store = WebConfigStore(path)

    initial = store.load()
    assert initial["persisted"] is False
    assert [row["id"] for row in initial["providers"]["social_data"]] == ["bird", "reddit"]

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
