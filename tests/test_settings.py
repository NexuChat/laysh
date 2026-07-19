import pytest


def test_runtime_defaults_are_gpt_5_6_family_only():
    from server.settings import ALLOWED_RUNTIME_MODELS, Settings

    settings = Settings()
    assert settings.understand_model == "gpt-5.6-luna"
    assert {
        settings.understand_model,
        settings.understand_fallback_model,
        settings.generate_model,
        settings.heal_model,
        settings.qa_model,
    } <= ALLOWED_RUNTIME_MODELS


def test_non_gpt_5_6_runtime_override_is_rejected(monkeypatch):
    from server.settings import Settings

    monkeypatch.setenv("LAYSH_UNDERSTAND_MODEL", "legacy-non-gpt-5.6-model")
    with pytest.raises(ValueError, match="GPT-5.6"):
        Settings.from_env()
