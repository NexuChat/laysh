import pytest


def test_runtime_defaults_are_gpt_5_6_family_only():
    from server.settings import ALLOWED_RUNTIME_MODELS, Settings

    settings = Settings()
    assert settings.understand_model == "gpt-5.6-luna"
    assert settings.evidence_understand_model == "gpt-5.6-sol"
    assert {
        settings.understand_model,
        settings.understand_fallback_model,
        settings.evidence_understand_model,
        settings.generate_model,
        settings.heal_model,
        settings.qa_model,
        settings.visual_qa_model,
    } <= ALLOWED_RUNTIME_MODELS
    assert settings.public_job_timeout_seconds == 180
    assert settings.evidence_job_timeout_seconds == 600
    assert settings.public_stage_timeout_seconds == 90
    assert settings.evidence_stage_timeout_seconds == 300
    assert settings.public_qa_timeout_seconds == 45
    assert settings.evidence_qa_timeout_seconds == 120
    assert settings.cache_key_secret == ""
    assert settings.record_runtime is False


def test_timeout_profiles_are_independently_configurable(monkeypatch):
    from server.settings import Settings

    monkeypatch.setenv("LAYSH_PUBLIC_JOB_TIMEOUT_SECONDS", "179")
    monkeypatch.setenv("LAYSH_EVIDENCE_JOB_TIMEOUT_SECONDS", "599")
    monkeypatch.setenv("LAYSH_PUBLIC_STAGE_TIMEOUT_SECONDS", "89")
    monkeypatch.setenv("LAYSH_EVIDENCE_STAGE_TIMEOUT_SECONDS", "299")
    monkeypatch.setenv("LAYSH_PUBLIC_QA_TIMEOUT_SECONDS", "44")
    monkeypatch.setenv("LAYSH_EVIDENCE_QA_TIMEOUT_SECONDS", "119")

    settings = Settings.from_env()

    assert settings.public_job_timeout_seconds == 179
    assert settings.evidence_job_timeout_seconds == 599
    assert settings.public_stage_timeout_seconds == 89
    assert settings.evidence_stage_timeout_seconds == 299
    assert settings.public_qa_timeout_seconds == 44
    assert settings.evidence_qa_timeout_seconds == 119


def test_non_gpt_5_6_runtime_override_is_rejected(monkeypatch):
    from server.settings import Settings

    monkeypatch.setenv("LAYSH_UNDERSTAND_MODEL", "legacy-non-gpt-5.6-model")
    with pytest.raises(ValueError, match="GPT-5.6"):
        Settings.from_env()
