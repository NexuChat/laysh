from __future__ import annotations

import hashlib
import json
import subprocess
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request

import pytest
from pydantic import ValidationError

COMMIT = "a" * 40


def _show(**overrides: str) -> str:
    values = {
        "Id": "laysh.service",
        "LoadState": "loaded",
        "ActiveState": "active",
        "SubState": "running",
        "UnitFileState": "enabled",
        "Result": "success",
        "ExecMainStatus": "0",
        "WorkingDirectory": "/srv/laysh",
        "ExecStart": (
            "{ path=/srv/laysh/.venv/bin/uvicorn ; "
            "argv[]=/srv/laysh/.venv/bin/uvicorn server.app:app ; }"
        ),
    }
    values.update(overrides)
    return "".join(f"{key}={value}\n" for key, value in values.items())


def _gallery_body(count: int = 6) -> bytes:
    return json.dumps(
        {
            "contract_version": "1.0",
            "lessons": [
                {
                    "id": f"lesson-{index}",
                    "title": f"درس {index}",
                    "domain": "العلوم",
                    "summary": "ملخص",
                    "instant": True,
                    "tier": "A",
                }
                for index in range(count)
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()


class _Response:
    def __init__(self, body: bytes, *, status: int = 200) -> None:
        self._body = body
        self.status = status

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]


def _dependencies(*, gallery_count: int = 6):
    from scripts.capture_release_service import HEALTH_SERVICE, HEALTH_TIMER, MAIN_SERVICE

    calls: list[tuple[list[str], dict[str, object]]] = []
    responses = {
        "http://127.0.0.1:8765/healthz": json.dumps(
            {"status": "ok", "backend": "codex", "queue": {"active": 0}},
            separators=(",", ":"),
        ).encode(),
        "http://127.0.0.1:8765/api/gallery?locale=ar": _gallery_body(gallery_count),
    }

    show_output = {
        MAIN_SERVICE: _show(),
        HEALTH_TIMER: _show(
            Id=HEALTH_TIMER,
            ActiveState="active",
            SubState="waiting",
            WorkingDirectory="",
            ExecStart="",
            ExecMainStatus="0",
        ),
        HEALTH_SERVICE: _show(
            Id=HEALTH_SERVICE,
            ActiveState="inactive",
            SubState="dead",
            UnitFileState="static",
            WorkingDirectory="/srv/laysh",
            ExecStart=(
                "{ path=/srv/laysh/.venv/bin/python ; "
                "argv[]=/srv/laysh/.venv/bin/python scripts/healthcheck.py ; }"
            ),
        ),
    }

    def run(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((list(arguments), kwargs))
        if arguments[:3] == ["/usr/bin/git", "-C", "/srv/laysh"]:
            return subprocess.CompletedProcess(arguments, 0, f"{COMMIT}\n", "")
        unit = arguments[3]
        operation = arguments[2]
        if operation == "is-active":
            active = unit != HEALTH_SERVICE
            return subprocess.CompletedProcess(
                arguments,
                0 if active else 3,
                "active\n" if active else "inactive\n",
                "",
            )
        assert operation == "show"
        return subprocess.CompletedProcess(arguments, 0, show_output[unit], "")

    def open_url(request: Request, *, timeout: int) -> _Response:
        assert request.get_method() == "GET"
        assert timeout == 5
        return _Response(responses[request.full_url])

    return run, open_url, calls, responses


def test_capture_records_raw_systemd_http_commit_and_six_instant_tier_a_cards() -> None:
    from scripts.capture_release_service import (
        capture_release_service,
        validate_gallery_receipt,
        validate_health_receipt,
    )

    run, open_url, calls, responses = _dependencies()
    health, gallery = capture_release_service(
        repository_root=Path("/srv/laysh"),
        port=8765,
        run_command=run,
        open_url=open_url,
        now=lambda: datetime(2026, 7, 21, 20, 15, tzinfo=UTC),
    )

    validate_health_receipt(health)
    validate_gallery_receipt(gallery)
    assert health["commit"] == gallery["commit"] == COMMIT
    assert set(health["commands"]) == {
        "service_is_active",
        "service_show",
        "health_timer_is_active",
        "health_timer_show",
        "health_service_is_active",
        "health_service_show",
    }
    assert "WorkingDirectory=/srv/laysh" in health["commands"]["service_show"]["stdout"]
    assert (
        "ExecStart={ path=/srv/laysh/.venv/bin/uvicorn"
        in health["commands"]["service_show"]["stdout"]
    )
    assert health["http"]["status"] == 200
    assert (
        health["http"]["body_sha256"]
        == hashlib.sha256(responses[health["http"]["url"]]).hexdigest()
    )
    assert (
        gallery["http"]["body_sha256"]
        == hashlib.sha256(responses[gallery["http"]["url"]]).hexdigest()
    )

    systemctl_calls = [item for item in calls if item[0][0] == "/usr/bin/systemctl"]
    assert len(systemctl_calls) == 6
    assert all(item[0][1] == "--user" for item in systemctl_calls)
    assert all(
        kwargs
        == {
            "check": False,
            "capture_output": True,
            "text": True,
            "timeout": 10,
            "shell": False,
        }
        for _, kwargs in calls
    )
    show_argv = health["commands"]["service_show"]["argv"]
    assert show_argv[:4] == ["/usr/bin/systemctl", "--user", "show", "laysh.service"]
    assert "WorkingDirectory" in show_argv[-1]
    assert "ExecStart" in show_argv[-1]
    assert gallery["http"]["request_command"] == [
        "GET",
        "http://127.0.0.1:8765/api/gallery?locale=ar",
    ]


def test_closed_receipts_reject_claims_without_replayable_raw_evidence() -> None:
    from scripts.capture_release_service import (
        capture_release_service,
        validate_gallery_receipt,
        validate_health_receipt,
    )

    run, open_url, _, _ = _dependencies()
    health, gallery = capture_release_service(
        repository_root=Path("/srv/laysh"),
        run_command=run,
        open_url=open_url,
    )

    with pytest.raises(ValidationError):
        validate_health_receipt(
            {
                "schema_version": "1.0",
                "gate": "service",
                "commit": COMMIT,
                "passed": True,
                "active": True,
                "healthz_green": True,
            }
        )
    extra = deepcopy(gallery)
    extra["instant_gallery_passed"] = True
    with pytest.raises(ValidationError):
        validate_gallery_receipt(extra)


@pytest.mark.parametrize(
    ("mutation", "validator"),
    [
        (lambda health, _gallery: health["http"].update(body_sha256="0" * 64), "health"),
        (
            lambda health, _gallery: health["commands"]["service_show"].update(stdout="forged"),
            "health",
        ),
        (lambda _health, gallery: gallery["http"].update(status=503), "gallery"),
        (
            lambda _health, gallery: gallery["http"].update(
                url="http://127.0.0.1:8765/api/gallery?locale=en"
            ),
            "gallery",
        ),
    ],
)
def test_receipt_validation_fails_closed_on_tampered_raw_measurements(
    mutation,
    validator: str,
) -> None:
    from scripts.capture_release_service import (
        capture_release_service,
        validate_gallery_receipt,
        validate_health_receipt,
    )

    run, open_url, _, _ = _dependencies()
    health, gallery = capture_release_service(
        repository_root=Path("/srv/laysh"),
        run_command=run,
        open_url=open_url,
    )
    mutation(health, gallery)

    with pytest.raises((ValidationError, ValueError)):
        (validate_health_receipt if validator == "health" else validate_gallery_receipt)(
            health if validator == "health" else gallery
        )


def test_gallery_receipt_requires_exactly_six_unique_instant_tier_a_cards() -> None:
    from scripts.capture_release_service import capture_release_service

    run, open_url, _, _ = _dependencies(gallery_count=5)

    with pytest.raises(ValueError, match="six unique instant Tier-A"):
        capture_release_service(
            repository_root=Path("/srv/laysh"),
            run_command=run,
            open_url=open_url,
        )


def test_capture_writes_two_atomic_closed_receipts(tmp_path: Path) -> None:
    from scripts.capture_release_service import capture_and_write

    run, open_url, _, _ = _dependencies()
    health_path = tmp_path / "release-service-health.json"
    gallery_path = tmp_path / "release-service-gallery.json"

    capture_and_write(
        health_path=health_path,
        gallery_path=gallery_path,
        repository_root=Path("/srv/laysh"),
        run_command=run,
        open_url=open_url,
    )

    assert json.loads(health_path.read_text(encoding="utf-8"))["gate"] == "service"
    assert json.loads(gallery_path.read_text(encoding="utf-8"))["gate"] == "service_gallery"
    assert not health_path.with_suffix(".json.tmp").exists()
    assert not gallery_path.with_suffix(".json.tmp").exists()
