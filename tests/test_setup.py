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
