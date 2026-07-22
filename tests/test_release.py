from __future__ import annotations

import json
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
    assert "ProtectHome=read-only" in service
    assert "ReadWritePaths=%h/.codex" in service
    assert "EnvironmentFile=-%h/.config/laysh/service.env" in service
    assert "LAYSH_CODEX_BACKEND=codex" in service
    assert "gpt-5.6-luna" in service
    assert service.count("gpt-5.6-sol") >= 3
    assert "LAYSH_UNDERSTAND_FALLBACK_MODEL=gpt-5.6-terra" in service
    assert "LAYSH_QA_MODEL=gpt-5.6-sol" in service
    assert "LAYSH_TERRA_GENERATION_TIERS=" in service
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
        "https://laysh.mlki.app",
        "https://github.com/NexuChat/laysh",
        "How I collaborated with Codex",
        "Quota protection",
    ):
        assert required in readme
    assert "MIT License" in license_text
    assert "GNU FreeFont" in notices and "Font Exception" in notices
    assert "Noto Kufi Arabic" in notices and "SIL Open Font License" in notices
    assert "Education" in submission
    assert "019f7998-9378-72b2-b590-ee10e632ce81" in submission
    assert "https://github.com/NexuChat/laysh" in submission
    assert "https://laysh.mlki.app" in submission
    assert "https://youtu.be/KRztDZH5BEQ" in submission
    assert "authenticated Devpost confirmation" in submission


def test_release_version_is_consistently_1_1_0():
    assert 'version = "1.1.0"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"version": "1.1.0"' in (ROOT / "package.json").read_text(encoding="utf-8")
    assert 'version="1.1.0"' in (ROOT / "server" / "app.py").read_text(encoding="utf-8")
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert 'name = "laysh"\nversion = "1.1.0"' in lock


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


def test_g6_evidence_records_service_clean_checkout_and_owner_boundary_honestly():
    verdict = json.loads(
        (ROOT / "out" / "evidence" / "g6-verdict.json").read_text(encoding="utf-8")
    )
    clean = json.loads(
        (ROOT / "out" / "evidence" / "g6-clean-checkout.json").read_text(
            encoding="utf-8"
        )
    )
    service = json.loads(
        (ROOT / "out" / "evidence" / "g6-service.json").read_text(encoding="utf-8")
    )
    gallery = json.loads(
        (ROOT / "out" / "evidence" / "g6-service-gallery.json").read_text(
            encoding="utf-8"
        )
    )

    assert verdict["verdict"] == "pass" and verdict["live_model_calls_in_m6"] == 0
    assert verdict["acceptance_matrix"] == {
        "p0_rows_total": 73,
        "green_in_builder_scope": 68,
        "failing_in_builder_scope": 0,
        "unknown": 0,
        "prepared_owner_only": verdict["acceptance_matrix"]["prepared_owner_only"],
    }
    assert len(verdict["acceptance_matrix"]["prepared_owner_only"]) == 5
    assert clean["passed"] is True and clean["tracked_status_clean"] is True
    assert service["passed"] is True and service["systemd_user"]["health_timer"][
        "latest_result"
    ] == "success"
    assert len(gallery["cards"]) == len(gallery["journeys"]) == 6
    assert gallery["askPosts"] == gallery["externalRequests"] == 0
