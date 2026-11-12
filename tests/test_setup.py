from fastapi import HTTPException

from app import desktop_routes


def test_deepseek_probe_checks_the_saved_key(monkeypatch):
    monkeypatch.setattr(desktop_routes.config, "credentials", lambda: {"TRANSLATE_API_KEY": "k"})
    monkeypatch.setattr(desktop_routes.config, "settings", lambda: {"ai_model": "deepseek-chat"})

    class Response:
        status_code = 200

    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: Response())
    assert desktop_routes.test_deepseek() == {"ok": True, "model": "deepseek-chat"}
    monkeypatch.setattr(desktop_routes.config, "credentials", lambda: {"TRANSLATE_API_KEY": ""})
    try:
        desktop_routes.test_deepseek()
    except HTTPException as error:
        assert error.status_code == 400
    else:
        raise AssertionError("expected a missing key")


def test_guide_completion_is_persisted_independently_of_browser_storage(tmp_path, monkeypatch):
    config = desktop_routes.config
    monkeypatch.setattr(config, 'HOME', tmp_path)
    monkeypatch.setattr(config, 'SETTINGS', tmp_path/'settings.json')
    monkeypatch.setattr(config, 'credentials', lambda: {key:'' for key in config.CREDENTIALS})
    desktop_routes.save_settings(desktop_routes.Preferences(onboarding_complete=True))
    assert config.settings()['onboarding_complete'] is True
    assert desktop_routes.settings()['onboarding_complete'] is True
