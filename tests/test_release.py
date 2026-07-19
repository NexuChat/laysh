from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
SESSION_ID = "019f7998-9378-72b2-b590-ee10e632ce81"


def test_deployment_units_are_secret_free_persistent_and_health_checked():
    service = (ROOT / "deploy" / "laysh.service").read_text(encoding="utf-8")
    health_service = (ROOT / "deploy" / "laysh-healthcheck.service").read_text(
        encoding="utf-8"
    )
    timer = (ROOT / "deploy" / "laysh-healthcheck.timer").read_text(encoding="utf-8")
    serve = (ROOT / "scripts" / "serve.sh").read_text(encoding="utf-8")

    assert "WantedBy=default.target" in service
    assert "Restart=always" in service
    assert "EnvironmentFile=-%h/.config/laysh/service.env" in service
    assert "LAYSH_CODEX_BACKEND=codex" in service
    assert "gpt-5.6-luna" in service and service.count("gpt-5.6-sol") >= 4
    assert "LAYSH_CACHE_KEY_SECRET=" not in service
    assert "127.0.0.1:8765/healthz" in health_service
    assert "scripts/healthcheck.py" in health_service
    assert "OnActiveSec=30s" in timer
    assert "OnBootSec=" not in timer
    assert "OnUnitActiveSec=5min" in timer
    assert "WantedBy=timers.target" in timer
    assert "uvicorn" in serve and "exec" in serve
    combined = service + health_service + timer + serve
    assert not re.search(r"(?i)(api[_-]?key|token|password)\s*=\s*[^\s$%]", combined)


def test_release_documents_cover_judge_and_owner_handoff_requirements():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    submission = (ROOT / "docs" / "submission" / "README.md").read_text(encoding="utf-8")
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

    for required in (
        "اسأل ليش، والعب الجواب",
        "Ask why. Play the answer.",
        SESSION_ID,
        "25.3",
        "178.3",
        "/home/dev/fahim",
        "gpt-5.6-luna",
        "gpt-5.6-sol",
        "FINAL-DEMO-URL",
        "FINAL-REPOSITORY-URL",
        "How I collaborated with Codex",
        "Quota protection",
    ):
        assert required in readme
    assert "MIT License" in license_text
    assert "GNU FreeFont" in notices and "Font Exception" in notices
    assert "Education" in submission
    assert "019f7998-9378-72b2-b590-ee10e632ce81" in submission
    assert "Create the public GitHub repository" in submission
    assert "Upload the final video" in submission
    assert "Submit" in submission


def test_release_version_is_consistently_1_0_0():
    assert 'version = "1.0.0"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"version": "1.0.0"' in (ROOT / "package.json").read_text(encoding="utf-8")
    assert 'version="1.0.0"' in (ROOT / "server" / "app.py").read_text(encoding="utf-8")
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert 'name = "laysh"\nversion = "1.0.0"' in lock


def test_runtime_configuration_and_release_docs_name_only_gpt56_runtime_models():
    runtime_files = [
        ROOT / ".env.example",
        ROOT / "server" / "settings.py",
        ROOT / "deploy" / "laysh.service",
        ROOT / "README.md",
        ROOT / "docs" / "submission" / "README.md",
    ]
    banned = re.compile(
        r"gpt-(?!5\.6-(?:luna|sol|terra)\b)\d+(?:\.\d+)*-[a-z0-9.-]+",
        re.IGNORECASE,
    )
    for path in runtime_files:
        assert not banned.search(path.read_text(encoding="utf-8")), path
