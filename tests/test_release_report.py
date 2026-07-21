from __future__ import annotations

import ast
import hashlib
import json
import struct
import subprocess
import xml.etree.ElementTree as ET
import zlib
from copy import deepcopy
from pathlib import Path

import pytest


def _row_ids() -> tuple[str, ...]:
    from scripts.verify_release import EXPECTED_ACCEPTANCE_ROWS

    return EXPECTED_ACCEPTANCE_ROWS


def _git(repository_root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _git_bytes(repository_root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository_root,
        check=True,
        capture_output=True,
    )
    return completed.stdout


def _initialize_repository(repository_root: Path) -> str:
    from scripts.evaluate_generation_routing import PRIOR_ABORTED_EVIDENCE_PATHS

    repository_root.mkdir(parents=True)
    _git(repository_root, "init", "--quiet")
    _git(repository_root, "config", "user.email", "release-test@example.invalid")
    _git(repository_root, "config", "user.name", "Release Test")
    (repository_root / "source.txt").write_text("release source\n", encoding="utf-8")
    _git(repository_root, "add", "source.txt")
    source_root = Path(__file__).parents[1]
    for relative in PRIOR_ABORTED_EVIDENCE_PATHS:
        destination = repository_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((source_root / relative).read_bytes())
        _git(repository_root, "add", relative)
    _git(repository_root, "commit", "--quiet", "-m", "test: release source")
    return _git(repository_root, "rev-parse", "HEAD")


def _write_json(repository_root: Path, relative: str, document: object) -> None:
    path = repository_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def _valid_png(*, width: int = 2, height: int = 2) -> bytes:
    row = b"\x00" + (b"\x20\x40\x60\xff" * width)
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(
                b"IHDR",
                struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0),
            ),
            _png_chunk(b"IDAT", zlib.compress(row * height)),
            _png_chunk(b"IEND", b""),
        )
    )


def _raw_command_receipt(
    argv: list[str], *, stdout: str, stderr: str = "", exit_code: int = 0
) -> dict[str, object]:
    return {
        "argv": argv,
        "exit_code": exit_code,
        "stdout": stdout,
        "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
        "stderr": stderr,
        "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
    }


def _http_receipt(url: str, body: object) -> dict[str, object]:
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return {
        "method": "GET",
        "url": url,
        "status": 200,
        "body": encoded,
        "body_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
        "request_command": ["GET", url],
    }


def _materialize_clean_checkout(
    repository_root: Path, document: dict[str, object], commit: str
) -> None:
    from scripts.verify_clean_checkout import ARCHIVE_PATH, JUNIT_PATH

    clean = document["clean_checkout"]
    junit_relative = JUNIT_PATH
    junit_nodeids = [
        "tests/test_release_probe.py::test_probe_0",
        "tests/test_release_probe.py::test_probe_1",
        "tests/test_release_probe.py::test_probe_2",
    ]
    cases = "".join(
        f'<testcase classname="release" file="{nodeid.split("::", 1)[0]}" '
        f'name="{nodeid.split("::", 1)[1]}" />'
        for nodeid in junit_nodeids
    )
    junit_path = repository_root / junit_relative
    junit_path.parent.mkdir(parents=True, exist_ok=True)
    junit_path.write_text(
        f'<testsuite tests="3" failures="0" errors="0" skipped="0">{cases}'
        "</testsuite>\n",
        encoding="utf-8",
    )
    tree_oid = _git(repository_root, "rev-parse", f"{commit}^{{tree}}")
    tree_sha256 = hashlib.sha256(tree_oid.encode()).hexdigest()
    archive_relative = ARCHIVE_PATH
    archive_bytes = _git_bytes(repository_root, "archive", "--format=tar", commit)
    archive_path = repository_root / archive_relative
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(archive_bytes)
    command_specs = {
        "pytest": (
            [
                "../venv/bin/python",
                "-m",
                "pytest",
                "-q",
                "-m",
                "not live",
                f"--junitxml=../evidence/{Path(junit_relative).name}",
            ],
            "3 passed\n",
        ),
        "ruff": (["../venv/bin/ruff", "check", "."], "All checks passed!\n"),
        "static_assets": (
            ["../venv/bin/python", "scripts/freeze_static_assets.py", "--check"],
            "static assets match manifest\n",
        ),
        "no_example_specific_runtime": (
            [
                "../venv/bin/python",
                "scripts/check_no_example_specific_runtime.py",
                ".",
            ],
            "[]\n",
        ),
        "status": (["git", "status", "--short", "--untracked-files=all"], ""),
    }
    commands = [
        {
            **_raw_command_receipt(argv, stdout=stdout),
            "name": name,
            "cwd": "$CLEAN_CHECKOUT",
            "duration_seconds": 0.01,
        }
        for name, (argv, stdout) in command_specs.items()
    ]
    _write_json(
        repository_root,
        clean["evidence_path"],
        {
            "schema_version": "1.0",
            "gate": "clean_checkout",
            **clean,
            "commit": commit,
            "source": "git_archive",
            "source_commit": commit,
            "source_tree_oid": tree_oid,
            "source_tree_sha256": tree_sha256,
            "archive": {
                "path": archive_relative,
                "sha256": hashlib.sha256(archive_bytes).hexdigest(),
                "commit": commit,
                "tree_oid": tree_oid,
                "file_count": len(
                    _git(repository_root, "ls-tree", "-r", "--name-only", commit).splitlines()
                ),
            },
            "commands": commands,
            "junit_path": junit_relative,
            "junit_sha256": hashlib.sha256(junit_path.read_bytes()).hexdigest(),
            "junit_nodeids": junit_nodeids,
            "model_calls": 0,
        },
    )


def _pytest_suite(name: str, commit: str, *, skipped: int = 0) -> dict[str, object]:
    from scripts.verify_release import ACCEPTANCE_ROW_TEST_NODEIDS

    acceptance_nodeids = {
        nodeid
        for nodeids in ACCEPTANCE_ROW_TEST_NODEIDS.values()
        for nodeid in nodeids
    }
    return {
        "name": name,
        "command": f"pytest {name}",
        "passed": True,
        "tests_passed": len(acceptance_nodeids) if name == "unit_integration" else 2,
        "failures": 0,
        "errors": 0,
        "skipped": skipped,
        "skip_explanations": (
            ["live model spend remains opt-in"] if skipped else []
        ),
        "duration_seconds": 310.25,
        "junit_path": f"out/evidence/release-{name}.junit.xml",
        "commit": commit,
    }


def _routing_case(fixture_id: str, model: str, *, passed: bool) -> dict[str, object]:
    spec_sha256 = hashlib.sha256(fixture_id.encode()).hexdigest()
    return {
        "fixture_id": fixture_id,
        "spec_sha256": spec_sha256,
        "generation_model": model,
        "passed": passed,
        "elapsed_ms": 1000,
        "live_calls": [
            {
                "stage": "generate",
                "model": model,
                "effort": "medium",
                "why_model_was_called": "fixed_spec_candidate",
                "elapsed_ms": 1000,
                "outcome": "completed",
                "thread_id_captured": True,
                "failure_code": None,
                "input_tokens": 100,
                "cached_input_tokens": 20,
                "output_tokens": 40,
            }
        ],
        "heal_count": 0,
        "failure_code": None if passed else "deterministic_verification_failed",
    }


def _routing_provenance(commit: str, head_tree_sha256: str) -> dict[str, object]:
    from scripts.evaluate_generation_routing import FIXTURE_IDS

    return {
        "head_commit": commit,
        "head_tree_sha256": head_tree_sha256,
        "worktree_state_sha256": hashlib.sha256(b"").hexdigest(),
        "worktree_dirty": False,
        "source_snapshot_sha256": "3" * 64,
        "evaluator_sha256": "4" * 64,
        "runtime_sha256": "5" * 64,
        "generate_prompt_sha256": "6" * 64,
        "heal_prompt_sha256": "7" * 64,
        "qa_prompt_sha256": "8" * 64,
        "module_verifier_sha256": "9" * 64,
        "server_verifier_sha256": "a" * 64,
        "fixture_prompt_fingerprints": [
            {
                "fixture_id": fixture_id,
                "payload_sha256": hashlib.sha256(fixture_id.encode()).hexdigest(),
            }
            for fixture_id in FIXTURE_IDS
        ],
    }


def _routing_report(
    repository_root: Path,
    commit: str,
    head_tree_sha256: str,
) -> dict[str, object]:
    from scripts.evaluate_generation_routing import (
        FIXTURE_IDS,
        PRIOR_ABORTED_EVIDENCE_PATHS,
        build_report_from_raw,
    )

    cases = [
        _routing_case(FIXTURE_IDS[0], "gpt-5.6-terra", passed=False),
        _routing_case(FIXTURE_IDS[1], "gpt-5.6-terra", passed=True),
        _routing_case(FIXTURE_IDS[0], "gpt-5.6-sol", passed=True),
        _routing_case(FIXTURE_IDS[1], "gpt-5.6-sol", passed=True),
    ]
    provenance = _routing_provenance(commit, head_tree_sha256)
    raw = {
        "schema_version": "1.0",
        "acceptance_row": "ROUTE-02",
        "sanitized": True,
        "call_cap": 12,
        "status": "complete",
        "active_model": "gpt-5.6-sol",
        "evaluation_provenance": provenance,
        "cases": cases,
        "usage_observations": [
            {
                "model": "gpt-5.6-terra",
                "source": "codex_app_server_account_usage_read",
                "delta_units": 500,
                "turn_reported_tokens": 400,
                "sample_count": 2,
                "observed_before_at": "2026-07-21T19:00:00Z",
                "observed_after_at": "2026-07-21T19:01:00Z",
            },
            {
                "model": "gpt-5.6-sol",
                "source": "codex_app_server_account_usage_read",
                "delta_units": 600,
                "turn_reported_tokens": 500,
                "sample_count": 2,
                "observed_before_at": "2026-07-21T19:02:00Z",
                "observed_after_at": "2026-07-21T19:03:00Z",
            },
        ],
        "inflight": None,
    }
    raw_path = repository_root / "out/evidence/route-02-raw.json"
    _write_json(repository_root, "out/evidence/route-02-raw.json", raw)
    _git(repository_root, "add", raw_path.relative_to(repository_root).as_posix())
    source_root = Path(__file__).parents[1]
    for relative in PRIOR_ABORTED_EVIDENCE_PATHS:
        destination = repository_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((source_root / relative).read_bytes())
        _git(repository_root, "add", relative)
    decision_path = repository_root / "server/routing_decision.json"
    _write_json(
        repository_root,
        "server/routing_decision.json",
        {"schema_version": "1.0", "terra_generation_tiers": []},
    )
    return build_report_from_raw(
        raw,
        current_provenance=provenance,
        routing_decision_path=decision_path,
        raw_evidence_path=raw_path,
        repository_root=repository_root,
    )


def _release_evidence(commit: str) -> dict[str, object]:
    rows = [
        {
            "id": row_id,
            "status": "not-started" if row_id == "RELEASE-01" else "passing",
            "evidence_paths": (
                []
                if row_id == "RELEASE-01"
                else [f"out/evidence/acceptance/{row_id.lower()}.json"]
            ),
        }
        for row_id in _row_ids()
    ]
    return {
        "schema_version": "1.0",
        "captured_at_utc": "2026-07-21T20:15:00Z",
        "commit": commit,
        "acceptance_rows": rows,
        "unit_integration": _pytest_suite("unit_integration", commit, skipped=1),
        "coverage": {
            "command": "coverage run -m pytest -m 'not browser and not live'",
            "passed": True,
            "tests_passed": 3,
            "deselected": 20,
            "percent": 82.0,
            "baseline_percent": 90.01,
            "baseline_drop_explanation": "New browser-heavy continuation code is excluded.",
            "json_path": "out/evidence/release-coverage.json",
            "commit": commit,
        },
        "browser": _pytest_suite("browser", commit),
        "accessibility": {
            "command": "pytest -m accessibility",
            "passed": True,
            "tests_passed": 6,
            "failures": 0,
            "skipped": 0,
            "violations": 0,
            "evidence_path": "out/evidence/release-a11y.json",
            "commit": commit,
        },
        "quality": {
            "ruff_passed": True,
            "diff_check_passed": True,
            "no_example_specific_runtime_passed": True,
            "no_example_specific_runtime_violations": 0,
            "session_provenance_passed": True,
            "session_roots": 1,
            "merge_commits": 0,
            "unlinked_commits": 0,
            "evidence_paths": [
                "out/evidence/release-quality.json",
                "out/evidence/release-provenance.json",
            ],
            "commit": commit,
        },
        "gold": {
            "passed": True,
            "golden_count": 6,
            "locale_journey_count": 12,
            "screenshot_count": 24,
            "model_calls": 0,
            "evidence_path": "out/evidence/gold-01.json",
            "commit": commit,
        },
        "routing": {
            "passed": True,
            "route_01_passed": True,
            "route_02_passed": True,
            "decision_applied": True,
            "generation_model": "gpt-5.6-sol",
            "cohort_live_calls": 4,
            "prior_aborted_live_calls": 2,
            "total_live_calls": 6,
            "evidence_path": "out/evidence/route-02-routing-evaluation.json",
            "commit": commit,
        },
        "service": {
            "passed": True,
            "active": True,
            "restarted_commit": commit,
            "healthz_green": True,
            "gallery_count": 6,
            "instant_gallery_passed": True,
            "health_evidence_path": "out/evidence/release-service.json",
            "gallery_evidence_path": "out/evidence/release-service-gallery.json",
            "commit": commit,
        },
        "asset": {
            "passed": True,
            "manifest_compatible": True,
            "clean_browser_smoke_passed": True,
            "bundle_sha256": "b" * 64,
            "evidence_path": "out/evidence/release-assets.json",
            "commit": commit,
        },
        "clean_checkout": {
            "passed": True,
            "tracked_status_clean": True,
            "tests_passed": 3,
            "failures": 0,
            "ruff_passed": True,
            "evidence_path": "out/evidence/release-clean-checkout.json",
            "commit": commit,
        },
        "owner_boundary": {
            "owner_only_actions": [
                "create and push the public repository",
                "upload the final video",
                "submit the Education entry",
                "approve and create the release tag",
            ],
            "deviations": [],
            "risks": [],
            "next_actions": ["owner performs the explicitly reserved actions"],
        },
        "evidence_sha256": {},
    }


def _materialize_evidence(
    repository_root: Path,
    document: dict[str, object],
    *,
    golden_ids: tuple[str, ...] | None = None,
) -> None:
    commit = str(document["commit"])
    from scripts.verify_release import ACCEPTANCE_ROW_TEST_NODEIDS

    acceptance_nodeids = sorted(
        {
            nodeid
            for nodeids in ACCEPTANCE_ROW_TEST_NODEIDS.values()
            for nodeid in nodeids
        }
    )
    for suite_name in ("unit_integration", "browser"):
        suite = document[suite_name]
        junit = repository_root / suite["junit_path"]
        junit.parent.mkdir(parents=True, exist_ok=True)
        if suite_name == "unit_integration":
            cases = "".join(
                f'<testcase classname="release" file="{nodeid.split("::", 1)[0]}" '
                f'name="{nodeid.split("::", 1)[1]}" />'
                for nodeid in acceptance_nodeids
            )
        else:
            cases = "".join(
                f'<testcase classname="release" file="tests/browser_fixture.py" '
                f'name="test-browser-{index}" />'
                for index in range(suite["tests_passed"])
            )
        cases += "".join(
            f'<testcase classname="release" name="{suite_name}-skip-{index}">'
            '<skipped message="live model spend remains opt-in" />'
            "</testcase>"
            for index in range(suite["skipped"])
        )
        junit.write_text(
            (
                f'<testsuite tests="{suite["tests_passed"] + suite["skipped"]}" '
                f'failures="{suite["failures"]}" errors="{suite["errors"]}" '
                f'skipped="{suite["skipped"]}" time="{suite["duration_seconds"]}">'
                f"{cases}</testsuite>\n"
            ),
            encoding="utf-8",
        )

    unit_junit = document["unit_integration"]["junit_path"]
    unit_junit_sha256 = hashlib.sha256(
        (repository_root / unit_junit).read_bytes()
    ).hexdigest()
    for row in document["acceptance_rows"]:
        if row["id"] == "RELEASE-01":
            continue
        for relative in row["evidence_paths"]:
            _write_json(
                repository_root,
                relative,
                {
                    "schema_version": "1.0",
                    "gate": row["id"],
                    "passed": True,
                    "commit": commit,
                    "test_nodeids": list(ACCEPTANCE_ROW_TEST_NODEIDS[row["id"]]),
                    "source_evidence_sha256": {unit_junit: unit_junit_sha256},
                },
            )

    coverage = document["coverage"]
    _write_json(
        repository_root,
        coverage["json_path"],
        {"schema_version": "1.0", "gate": "coverage", **coverage},
    )
    a11y = document["accessibility"]
    _write_json(
        repository_root,
        a11y["evidence_path"],
        {"schema_version": "1.0", "gate": "accessibility", **a11y},
    )
    quality = document["quality"]
    _write_json(
        repository_root,
        quality["evidence_paths"][0],
        {
            "schema_version": "1.0",
            "gate": "quality",
            "commit": commit,
            "ruff_passed": quality["ruff_passed"],
            "diff_check_passed": quality["diff_check_passed"],
            "no_example_specific_runtime_passed": quality[
                "no_example_specific_runtime_passed"
            ],
            "no_example_specific_runtime_violations": quality[
                "no_example_specific_runtime_violations"
            ],
        },
    )
    _write_json(
        repository_root,
        quality["evidence_paths"][1],
        {
            "schema_version": "1.0",
            "passed": quality["session_provenance_passed"],
            "root_commit_count": quality["session_roots"],
            "merge_commit_count": quality["merge_commits"],
            "unlinked_commit_count": quality["unlinked_commits"],
            "commit": commit,
        },
    )

    if golden_ids is None:
        from server.goldens import GOLDEN_FIXTURE_IDS

        golden_ids = tuple(
            fixture_id.removesuffix("_ar") for fixture_id in GOLDEN_FIXTURE_IDS
        )
    if len(golden_ids) != 6 or len(set(golden_ids)) != 6:
        raise ValueError("release fixture needs exactly six golden identifiers")

    goldens = []
    manifest_lessons = []
    for index, golden_id in enumerate(golden_ids):
        artifact = f"<!doctype html><title>{golden_id}</title>"
        pinned_path = f"out/cache/golden/{golden_id}.json"
        _write_json(
            repository_root,
            pinned_path,
            {"schema_version": "1.0", "artifact": artifact},
        )
        artifact_hash = hashlib.sha256(artifact.encode()).hexdigest()
        document_hash = hashlib.sha256(
            (repository_root / pinned_path).read_bytes()
        ).hexdigest()
        manifest_lessons.append(
            {
                "id": golden_id,
                "aliases": [golden_id],
                "instant": True,
                "tier": "A",
                "artifact_sha256": artifact_hash,
                "metadata": {
                    "ar": {"title": golden_id, "domain": "علم", "summary": "ملخص"},
                    "en": {
                        "title": golden_id,
                        "domain": "Science",
                        "summary": "Summary",
                    },
                },
            }
        )
        screenshots = []
        locales = {}
        for locale in ("ar", "en"):
            localized = []
            for viewport in ("mobile", "desktop"):
                relative = (
                    f"out/evidence/screens/gold-01/{golden_id}-{locale}-{viewport}.png"
                )
                path = repository_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(
                    _valid_png(
                        width=2 if viewport == "mobile" else 3,
                        height=2 + index,
                    )
                )
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                record = {
                    "path": relative,
                    "sha256": digest,
                    "expected_sha256": digest,
                    "passed": True,
                }
                localized.append(record)
                screenshots.append(record)
            locales[locale] = {
                "passed": True,
                "lang": locale,
                "dir": "rtl" if locale == "ar" else "ltr",
                "screenshots": localized,
            }
        goldens.append(
            {
                "golden_id": golden_id,
                "passed": True,
                "tier": "A",
                "pinned": True,
                "artifact_sha256": artifact_hash,
                "document_sha256": document_hash,
                "manifest_hash_matches": True,
                "science": {"passed": True},
                "actor_motion": {"passed": True, "failures": []},
                "physics_motion": {"passed": True, "failures": []},
                "shared_state": {"passed": True, "failures": []},
                "locales": locales,
                "screenshots": screenshots,
                "failures": [],
            }
        )
    manifest_path = "out/cache/golden/manifest.json"
    _write_json(
        repository_root,
        manifest_path,
        {
            "schema_version": "1.0",
            "contract_version": "1.0",
            "lessons": manifest_lessons,
        },
    )
    manifest_hash = hashlib.sha256((repository_root / manifest_path).read_bytes()).hexdigest()
    gold = document["gold"]
    _write_json(
        repository_root,
        gold["evidence_path"],
        {
            "schema_version": "1.0",
            "gate": "GOLD-01",
            "passed": True,
            "golden_count": 6,
            "locale_journey_count": 12,
            "screenshot_count": 24,
            "check_count": 60,
            "model_calls": 0,
            "manifest": {
                "path": manifest_path,
                "sha256": manifest_hash,
                "schema_version": "1.0",
                "contract_version": "1.0",
                "golden_count": 6,
                "passed": True,
            },
            "goldens": goldens,
        },
    )

    routing = document["routing"]
    tree_oid = _git(repository_root, "rev-parse", "HEAD^{tree}")
    head_tree_sha256 = hashlib.sha256(tree_oid.encode()).hexdigest()
    _write_json(
        repository_root,
        routing["evidence_path"],
        _routing_report(repository_root, commit, head_tree_sha256),
    )
    service = document["service"]
    from scripts.capture_release_service import (
        SERVICE_SHOW_PROPERTIES,
        SYSTEMCTL,
        TIMER_SHOW_PROPERTIES,
    )

    service_show_properties = ",".join(SERVICE_SHOW_PROPERTIES)
    timer_show_properties = ",".join(TIMER_SHOW_PROPERTIES)
    service_commands = {
        "service_is_active": _raw_command_receipt(
            [SYSTEMCTL, "--user", "is-active", "laysh.service"],
            stdout="active\n",
        ),
        "service_show": _raw_command_receipt(
            [
                SYSTEMCTL,
                "--user",
                "show",
                "laysh.service",
                "--no-pager",
                f"--property={service_show_properties}",
            ],
            stdout=(
                "Id=laysh.service\nLoadState=loaded\nActiveState=active\n"
                "SubState=running\nUnitFileState=enabled\nResult=success\n"
                "ExecMainStatus=0\n"
                f"WorkingDirectory={repository_root}\n"
                f"ExecStart={{ path={repository_root}/scripts/serve.sh ; }}\n"
            ),
        ),
        "health_timer_is_active": _raw_command_receipt(
            [SYSTEMCTL, "--user", "is-active", "laysh-healthcheck.timer"],
            stdout="active\n",
        ),
        "health_timer_show": _raw_command_receipt(
            [
                SYSTEMCTL,
                "--user",
                "show",
                "laysh-healthcheck.timer",
                "--no-pager",
                f"--property={timer_show_properties}",
            ],
            stdout=(
                "Id=laysh-healthcheck.timer\nLoadState=loaded\nActiveState=active\n"
                "SubState=waiting\nUnitFileState=enabled\nResult=success\n"
            ),
        ),
        "health_service_is_active": _raw_command_receipt(
            [SYSTEMCTL, "--user", "is-active", "laysh-healthcheck.service"],
            stdout="inactive\n",
            exit_code=3,
        ),
        "health_service_show": _raw_command_receipt(
            [
                SYSTEMCTL,
                "--user",
                "show",
                "laysh-healthcheck.service",
                "--no-pager",
                f"--property={service_show_properties}",
            ],
            stdout=(
                "Id=laysh-healthcheck.service\nLoadState=loaded\n"
                "ActiveState=inactive\nSubState=dead\nUnitFileState=static\n"
                "Result=success\nExecMainStatus=0\n"
                f"WorkingDirectory={repository_root}\n"
                f"ExecStart={{ path={repository_root}/.venv/bin/python ; }}\n"
            ),
        ),
    }
    health_url = "http://127.0.0.1:8765/healthz"
    _write_json(
        repository_root,
        service["health_evidence_path"],
        {
            "schema_version": "1.0",
            "gate": "service",
            "captured_at_utc": "2026-07-21T20:14:00Z",
            "commit": commit,
            "commands": service_commands,
            "http": _http_receipt(
                health_url,
                {
                    "backend": "codex",
                    "queue": {"active": 0, "known_jobs": 0},
                    "status": "ok",
                },
            ),
        },
    )
    gallery_url = "http://127.0.0.1:8765/api/gallery?locale=ar"
    gallery_lessons = [
        {
            "id": f"golden-{index}",
            "title": f"درس {index}",
            "domain": "علم",
            "summary": "ملخص",
            "instant": True,
            "tier": "A",
        }
        for index in range(6)
    ]
    _write_json(
        repository_root,
        service["gallery_evidence_path"],
        {
            "schema_version": "1.0",
            "gate": "service_gallery",
            "captured_at_utc": "2026-07-21T20:14:01Z",
            "commit": commit,
            "http": _http_receipt(
                gallery_url,
                {"contract_version": "1.0", "lessons": gallery_lessons},
            ),
        },
    )
    from server.static_assets import RUNTIME_ASSETS, build_asset_manifest

    web_root = repository_root / "web"
    for relative in RUNTIME_ASSETS:
        path = web_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"asset:{relative}".encode())
    asset_manifest = build_asset_manifest(root=web_root)
    document["asset"]["bundle_sha256"] = asset_manifest["bundle_version"]
    _write_json(repository_root, "web/asset-manifest.json", asset_manifest)
    asset = document["asset"]
    _write_json(
        repository_root,
        asset["evidence_path"],
        {
            "schema_version": "1.0",
            "gate": "ASSET-01",
            **asset,
            "browser": {
                "passed": True,
                "response_count": len(RUNTIME_ASSETS),
                "console_errors": [],
            },
        },
    )
    _materialize_clean_checkout(repository_root, document, commit)
    _refresh_evidence_hashes(repository_root, document)


def _refresh_evidence_hashes(
    repository_root: Path, document: dict[str, object]
) -> None:
    references = {}
    for parent in (repository_root / "out", repository_root / "web"):
        if not parent.exists():
            continue
        for path in parent.rglob("*"):
            if path.is_file():
                relative = path.relative_to(repository_root).as_posix()
                references[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    document["evidence_sha256"] = dict(sorted(references.items()))


def _retarget_release_commit(
    repository_root: Path,
    document: dict[str, object],
    commit: str,
) -> None:
    document["commit"] = commit
    for section in (
        "unit_integration",
        "coverage",
        "browser",
        "accessibility",
        "quality",
        "gold",
        "routing",
        "service",
        "asset",
        "clean_checkout",
    ):
        document[section]["commit"] = commit
    document["service"]["restarted_commit"] = commit

    for row in document["acceptance_rows"]:
        for relative in row["evidence_paths"]:
            evidence = json.loads(
                (repository_root / relative).read_text(encoding="utf-8")
            )
            evidence["commit"] = commit
            _write_json(repository_root, relative, evidence)
    for section, path_field in (
        ("coverage", "json_path"),
        ("accessibility", "evidence_path"),
        ("asset", "evidence_path"),
    ):
        relative = document[section][path_field]
        evidence = json.loads(
            (repository_root / relative).read_text(encoding="utf-8")
        )
        evidence["commit"] = commit
        _write_json(repository_root, relative, evidence)
    for relative in document["quality"]["evidence_paths"]:
        evidence = json.loads(
            (repository_root / relative).read_text(encoding="utf-8")
        )
        evidence["commit"] = commit
        _write_json(repository_root, relative, evidence)

    health_relative = document["service"]["health_evidence_path"]
    health = json.loads(
        (repository_root / health_relative).read_text(encoding="utf-8")
    )
    health["commit"] = commit
    _write_json(repository_root, health_relative, health)
    gallery_relative = document["service"]["gallery_evidence_path"]
    gallery = json.loads(
        (repository_root / gallery_relative).read_text(encoding="utf-8")
    )
    gallery["commit"] = commit
    _write_json(repository_root, gallery_relative, gallery)

    _materialize_clean_checkout(repository_root, document, commit)
    _refresh_evidence_hashes(repository_root, document)


def _commit_release_source_then_evidence(
    repository_root: Path,
    document: dict[str, object],
) -> str:
    # ROUTE evidence is recorded after the immutable source commit.  The
    # release evidence can therefore be another evidence-only descendant, not
    # necessarily the direct child of the source commit.
    source_commit = str(document["commit"])
    _git(repository_root, "merge-base", "--is-ancestor", source_commit, "HEAD")
    _git(repository_root, "add", "out/evidence")
    _git(repository_root, "commit", "--quiet", "-m", "test: record release evidence")
    return source_commit


def _prepare_release_case(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    golden_ids: tuple[str, ...] | None = None,
) -> tuple[Path, dict[str, object]]:
    commit = _initialize_repository(root)
    document = _release_evidence(commit)
    _materialize_evidence(root, document, golden_ids=golden_ids)
    _git(root, "add", "out/cache/golden", "server/routing_decision.json", "web")
    _git(root, "commit", "--quiet", "-m", "test: bind release source")
    source_commit = _git(root, "rev-parse", "HEAD")
    _retarget_release_commit(root, document, source_commit)
    _materialize_evidence(root, document, golden_ids=golden_ids)
    _git(
        root,
        "add",
        document["routing"]["evidence_path"],
        "out/evidence/route-02-raw.json",
    )
    _git(root, "commit", "--quiet", "-m", "test: bind route evidence")
    route_report = json.loads(
        (root / document["routing"]["evidence_path"]).read_text(encoding="utf-8")
    )
    monkeypatch.setattr(
        "scripts.evaluate_generation_routing._evaluation_provenance",
        lambda: deepcopy(route_report["evaluation_provenance"]),
    )
    stable_fields = (
        "source_snapshot_sha256",
        "evaluator_sha256",
        "runtime_sha256",
        "generate_prompt_sha256",
        "heal_prompt_sha256",
        "qa_prompt_sha256",
        "module_verifier_sha256",
        "server_verifier_sha256",
        "fixture_prompt_fingerprints",
    )
    monkeypatch.setattr(
        "scripts.evaluate_generation_routing._provenance_content_fields",
        lambda _reader: {
            field: deepcopy(route_report["evaluation_provenance"][field])
            for field in stable_fields
        },
    )
    return root, document


@pytest.fixture
def release_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, dict[str, object]]:
    return _prepare_release_case(tmp_path / "repository", monkeypatch)


def _build(document: dict[str, object], repository_root: Path) -> dict[str, object]:
    from scripts.verify_release import build_release_report

    return build_release_report(document, repository_root=repository_root)


def test_release_acceptance_nodeid_map_resolves_to_real_tests():
    from scripts.verify_release import (
        ACCEPTANCE_ROW_TEST_NODEIDS,
        EXPECTED_ACCEPTANCE_ROWS,
    )

    assert set(ACCEPTANCE_ROW_TEST_NODEIDS) == set(EXPECTED_ACCEPTANCE_ROWS) - {
        "RELEASE-01"
    }
    for nodeids in ACCEPTANCE_ROW_TEST_NODEIDS.values():
        for nodeid in nodeids:
            relative, function = nodeid.split("::", 1)
            module = ast.parse(Path(relative).read_text(encoding="utf-8"))
            functions = {
                node.name
                for node in module.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            assert function in functions, nodeid


def test_release_report_closes_only_the_thirtieth_row_with_complete_evidence(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    report = _build(document, root)

    assert report["schema_version"] == "1.0"
    assert report["gate"] == "RELEASE-01"
    assert report["passed"] is True, report["failures"]
    assert report["acceptance"]["totals"] == {
        "total": 30,
        "passing": 30,
        "failing": 0,
        "not-started": 0,
        "blocked": 0,
    }
    assert len(report["acceptance"]["rows"]) == 30
    release = next(
        row for row in report["acceptance"]["rows"] if row["id"] == "RELEASE-01"
    )
    assert release == {
        "id": "RELEASE-01",
        "status": "passing",
        "evidence_paths": ["out/evidence/release-01.json"],
    }
    assert report["suites"]["unit_integration"]["skipped"] == 1
    assert report["suites"]["unit_integration"]["skip_explanations"] == [
        "live model spend remains opt-in"
    ]
    assert report["suites"]["coverage"]["percent"] == 82.0
    assert report["gold"]["golden_count"] == 6
    assert report["routing"]["decision_applied"] is True
    assert report["service"]["restarted_commit"] == document["commit"]
    assert report["failures"] == []


@pytest.mark.parametrize("status", ["failing", "not-started", "blocked"])
def test_release_report_never_hides_an_unclosed_prerequisite_row(
    status: str, release_case: tuple[Path, dict[str, object]]
):
    root, document = release_case
    document["acceptance_rows"][0]["status"] = status

    report = _build(document, root)

    assert report["passed"] is False
    assert report["acceptance"]["totals"][status] >= 1
    assert report["acceptance"]["totals"]["failing"] >= 1
    assert "acceptance_rows_not_all_passing" in {
        failure["code"] for failure in report["failures"]
    }


@pytest.mark.parametrize(
    ("mutation", "failure_code"),
    [
        (("unit_integration", "failures", 1), "unit_integration_failed"),
        (("coverage", "percent", 79.99), "coverage_below_80"),
        (("browser", "errors", 1), "browser_failed"),
        (("accessibility", "violations", 1), "accessibility_failed"),
        (("quality", "ruff_passed", False), "ruff_failed"),
        (
            ("quality", "no_example_specific_runtime_violations", 1),
            "example_specific_runtime_detected",
        ),
        (("quality", "session_roots", 2), "session_provenance_failed"),
        (("gold", "golden_count", 5), "gold_release_incomplete"),
        (("gold", "locale_journey_count", 11), "gold_release_incomplete"),
        (("gold", "screenshot_count", 23), "gold_release_incomplete"),
        (("routing", "decision_applied", False), "routing_not_applied"),
        (("service", "healthz_green", False), "service_not_green"),
        (("asset", "manifest_compatible", False), "asset_contract_failed"),
        (("clean_checkout", "tracked_status_clean", False), "clean_checkout_failed"),
    ],
)
def test_release_report_fails_closed_for_every_mandatory_gate(
    mutation: tuple[str, str, object],
    failure_code: str,
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    section, key, value = mutation
    document[section][key] = value

    report = _build(document, root)

    assert report["passed"] is False
    assert report["acceptance"]["totals"]["failing"] >= 1
    assert failure_code in {failure["code"] for failure in report["failures"]}


def test_release_report_rejects_missing_duplicate_or_unknown_acceptance_rows(
    release_case: tuple[Path, dict[str, object]],
):
    root, original = release_case
    missing = deepcopy(original)
    missing["acceptance_rows"] = missing["acceptance_rows"][:-1]
    with pytest.raises(ValueError, match="acceptance row set is not exact"):
        _build(missing, root)

    duplicate = deepcopy(original)
    duplicate["acceptance_rows"][-1] = deepcopy(duplicate["acceptance_rows"][0])
    with pytest.raises(ValueError, match="acceptance row set is not exact"):
        _build(duplicate, root)

    appended_duplicate = deepcopy(original)
    appended_duplicate["acceptance_rows"].append(
        deepcopy(appended_duplicate["acceptance_rows"][0])
    )
    with pytest.raises(ValueError, match="acceptance row set is not exact"):
        _build(appended_duplicate, root)

    unknown = deepcopy(original)
    unknown["acceptance_rows"][0]["id"] = "HIDDEN-01"
    with pytest.raises(ValueError, match="acceptance row set is not exact"):
        _build(unknown, root)


def test_release_report_rejects_silent_skips_unknown_fields_and_unsafe_paths(
    release_case: tuple[Path, dict[str, object]],
):
    root, original = release_case
    unexplained = deepcopy(original)
    unexplained["unit_integration"]["skip_explanations"] = []
    with pytest.raises(ValueError, match="skip explanations"):
        _build(unexplained, root)

    unknown = deepcopy(original)
    unknown["routing"]["raw_model_output"] = "must never enter release evidence"
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        _build(unknown, root)

    unsafe = deepcopy(original)
    unsafe["gold"]["evidence_path"] = "../../raw-learner-question.json"
    with pytest.raises(ValueError, match="repository-relative evidence path"):
        _build(unsafe, root)


def test_release_report_rejects_string_booleans_and_commit_drift(
    release_case: tuple[Path, dict[str, object]],
):
    root, original = release_case
    wrong_type = deepcopy(original)
    wrong_type["service"]["healthz_green"] = "true"
    with pytest.raises(ValueError):
        _build(wrong_type, root)

    drift = deepcopy(original)
    drift["service"]["commit"] = "c" * 40
    report = _build(drift, root)
    assert report["passed"] is False
    assert "evidence_commit_mismatch" in {
        failure["code"] for failure in report["failures"]
    }


def test_release_report_requires_named_evidence_for_every_passing_row(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    document["acceptance_rows"][0]["evidence_paths"] = []

    with pytest.raises(ValueError, match="passing acceptance row needs named evidence"):
        _build(document, root)


def test_release_report_rejects_a_passing_row_backed_by_a_failed_report(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    relative = document["acceptance_rows"][0]["evidence_paths"][0]
    evidence = json.loads((root / relative).read_text(encoding="utf-8"))
    evidence["passed"] = False
    _write_json(root, relative, evidence)
    _refresh_evidence_hashes(root, document)

    report = _build(document, root)

    assert report["passed"] is False
    assert "acceptance_evidence_mismatch" in {
        failure["code"] for failure in report["failures"]
    }


def test_release_report_rejects_missing_symlinked_or_hash_drifted_evidence(
    release_case: tuple[Path, dict[str, object]], tmp_path: Path
):
    root, original = release_case
    relative = original["unit_integration"]["junit_path"]
    path = root / relative

    missing = deepcopy(original)
    path.unlink()
    with pytest.raises(ValueError, match="evidence file is missing"):
        _build(missing, root)

    _materialize_evidence(root, original)
    outside = tmp_path / "outside-evidence.xml"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ValueError, match="evidence path uses a symlink"):
        _build(original, root)

    path.unlink()
    path.write_text("tampered after digest\n", encoding="utf-8")
    with pytest.raises(ValueError, match="evidence sha256 mismatch"):
        _build(original, root)


def test_release_report_rejects_an_arbitrary_non_head_commit(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    fake = "c" * 40
    document["commit"] = fake
    for section in (
        "unit_integration",
        "coverage",
        "browser",
        "accessibility",
        "quality",
        "gold",
        "routing",
        "service",
        "asset",
        "clean_checkout",
    ):
        document[section]["commit"] = fake
    document["service"]["restarted_commit"] = fake

    with pytest.raises(ValueError, match="release commit does not match HEAD"):
        _build(document, root)


def test_release_report_accepts_an_evidence_only_descendant_head(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    source_commit = _commit_release_source_then_evidence(root, document)

    report = _build(document, root)

    assert document["commit"] == source_commit
    assert _git(root, "rev-parse", "HEAD") != source_commit
    assert report["passed"] is True


def test_release_report_rejects_source_drift_after_its_bound_commit(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    _commit_release_source_then_evidence(root, document)
    (root / "source.txt").write_text("drift after release source\n", encoding="utf-8")
    _git(root, "add", "source.txt")
    _git(root, "commit", "--quiet", "-m", "test: forbidden source drift")

    with pytest.raises(ValueError, match="release commit does not match HEAD"):
        _build(document, root)


def test_release_report_rejects_a_spoofed_coverage_baseline(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    document["coverage"]["percent"] = 80.0
    document["coverage"]["baseline_percent"] = 0.0
    document["coverage"]["baseline_drop_explanation"] = ""
    coverage_path = root / document["coverage"]["json_path"]
    evidence = json.loads(coverage_path.read_text(encoding="utf-8"))
    evidence.update(document["coverage"])
    _write_json(root, document["coverage"]["json_path"], evidence)
    _refresh_evidence_hashes(root, document)

    with pytest.raises(ValueError, match="coverage baseline must remain 90.01"):
        _build(document, root)


def test_release_report_rejects_luna_or_zero_call_generation_routing(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    document["routing"]["generation_model"] = "gpt-5.6-luna"
    document["routing"]["cohort_live_calls"] = 0

    with pytest.raises(ValueError):
        _build(document, root)


def test_release_report_rejects_a_gold_report_with_a_failed_nested_gate(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    relative = document["gold"]["evidence_path"]
    evidence = json.loads((root / relative).read_text(encoding="utf-8"))
    evidence["goldens"][0]["actor_motion"]["passed"] = False
    _write_json(root, relative, evidence)
    _refresh_evidence_hashes(root, document)

    report = _build(document, root)

    assert report["passed"] is False
    assert "gold_release_incomplete" in {
        failure["code"] for failure in report["failures"]
    }


@pytest.mark.parametrize(
    ("section", "path_field", "failure_code"),
    [
        ("gold", "evidence_path", "gold_release_incomplete"),
        ("service", "health_evidence_path", "service_not_green"),
        ("asset", "evidence_path", "asset_contract_failed"),
        ("clean_checkout", "evidence_path", "clean_checkout_failed"),
    ],
)
def test_release_report_rejects_unsupported_summary_claims(
    section: str,
    path_field: str,
    failure_code: str,
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    relative = document[section][path_field]
    evidence = json.loads((root / relative).read_text(encoding="utf-8"))
    evidence["passed"] = False
    _write_json(root, relative, evidence)
    _refresh_evidence_hashes(root, document)

    report = _build(document, root)

    assert report["passed"] is False
    assert failure_code in {failure["code"] for failure in report["failures"]}


def test_release_report_rejects_tracked_source_dirty_against_head(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    (root / "source.txt").write_text("dirty tracked source\n", encoding="utf-8")

    with pytest.raises(ValueError, match="tracked source differs from HEAD"):
        _build(document, root)


def test_release_report_rejects_a_wrapper_around_failed_nested_evidence(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    relative = document["acceptance_rows"][0]["evidence_paths"][0]
    evidence = json.loads((root / relative).read_text(encoding="utf-8"))
    evidence["nested_report"] = {
        "passed": False,
        "failures": [{"code": "hidden_failure"}],
    }
    _write_json(root, relative, evidence)
    _refresh_evidence_hashes(root, document)

    report = _build(document, root)

    assert report["passed"] is False
    assert "acceptance_evidence_mismatch" in {
        failure["code"] for failure in report["failures"]
    }


def test_release_report_rejects_noncanonical_acceptance_test_nodeids(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    row = document["acceptance_rows"][0]
    relative = row["evidence_paths"][0]
    evidence = json.loads((root / relative).read_text(encoding="utf-8"))
    evidence["test_nodeids"] = [
        "tests/test_release_report.py::test_unrelated_self_claim"
    ]
    unit_junit = document["unit_integration"]["junit_path"]
    evidence["source_evidence_sha256"] = {
        unit_junit: hashlib.sha256((root / unit_junit).read_bytes()).hexdigest()
    }
    _write_json(root, relative, evidence)
    _refresh_evidence_hashes(root, document)

    report = _build(document, root)

    assert report["passed"] is False
    assert "acceptance_evidence_mismatch" in {
        failure["code"] for failure in report["failures"]
    }


def test_release_report_rejects_self_referential_acceptance_sources(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    row = document["acceptance_rows"][0]
    relative = row["evidence_paths"][0]
    evidence = json.loads((root / relative).read_text(encoding="utf-8"))
    evidence["test_nodeids"] = [
        "tests/test_session_provenance.py::"
        "test_root_session_manifest_matches_the_current_linear_history"
    ]
    evidence["source_evidence_sha256"] = {
        relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
    }
    _write_json(root, relative, evidence)
    _refresh_evidence_hashes(root, document)

    report = _build(document, root)

    assert report["passed"] is False
    assert "acceptance_evidence_mismatch" in {
        failure["code"] for failure in report["failures"]
    }


def test_release_report_rejects_junit_counts_without_testcase_records(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    suite = document["unit_integration"]
    path = root / suite["junit_path"]
    path.write_text(
        '<testsuite tests="4" failures="0" errors="0" skipped="1"></testsuite>\n',
        encoding="utf-8",
    )
    _refresh_evidence_hashes(root, document)

    with pytest.raises(ValueError, match="testcase count"):
        _build(document, root)


def test_release_report_rejects_a_required_nodeid_that_was_skipped(
    release_case: tuple[Path, dict[str, object]],
):
    from scripts.verify_release import ACCEPTANCE_ROW_TEST_NODEIDS

    root, document = release_case
    suite = document["unit_integration"]
    path = root / suite["junit_path"]
    tree = ET.parse(path)  # noqa: S314 - local synthetic JUnit fixture
    xml_root = tree.getroot()
    required = ACCEPTANCE_ROW_TEST_NODEIDS["BASE-01"][0]
    required_file, required_name = required.split("::", 1)
    testcase = next(
        item
        for item in xml_root.iter("testcase")
        if item.attrib.get("file") == required_file
        and item.attrib.get("name") == required_name
    )
    ET.SubElement(testcase, "skipped", {"message": "forced skip"})
    xml_root.attrib["skipped"] = str(int(xml_root.attrib["skipped"]) + 1)
    tree.write(path, encoding="unicode")
    suite["tests_passed"] -= 1
    suite["skipped"] += 1
    suite["skip_explanations"].append("forced skip")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    for row in document["acceptance_rows"]:
        for relative in row["evidence_paths"]:
            wrapper = json.loads((root / relative).read_text(encoding="utf-8"))
            wrapper["source_evidence_sha256"][suite["junit_path"]] = digest
            _write_json(root, relative, wrapper)
    _refresh_evidence_hashes(root, document)

    report = _build(document, root)

    assert report["passed"] is False
    assert "acceptance_evidence_mismatch" in {
        failure["code"] for failure in report["failures"]
    }


def test_release_report_accepts_the_real_gold_screenshot_record_shape(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    relative = document["gold"]["evidence_path"]
    report = json.loads((root / relative).read_text(encoding="utf-8"))
    assert all(
        isinstance(record, dict)
        for golden in report["goldens"]
        for record in golden["screenshots"]
    )

    release = _build(document, root)

    assert release["passed"] is True


def test_release_report_rejects_a_noncanonical_golden_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root, document = _prepare_release_case(
        tmp_path / "noncanonical-goldens",
        monkeypatch,
        golden_ids=tuple(f"lesson_{index}" for index in range(6)),
    )

    release = _build(document, root)

    assert release["passed"] is False
    assert "gold_release_incomplete" in {
        failure["code"] for failure in release["failures"]
    }


def test_release_report_rejects_screenshots_concentrated_in_one_golden(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    gold_path = document["gold"]["evidence_path"]
    report = json.loads((root / gold_path).read_text(encoding="utf-8"))
    all_screenshots = [
        deepcopy(record)
        for golden in report["goldens"]
        for record in golden["screenshots"]
    ]
    report["goldens"][0]["screenshots"] = all_screenshots
    report["goldens"][0]["locales"]["ar"]["screenshots"] = all_screenshots[:12]
    report["goldens"][0]["locales"]["en"]["screenshots"] = all_screenshots[12:]
    for golden in report["goldens"][1:]:
        golden["screenshots"] = []
        for locale in golden["locales"].values():
            locale["screenshots"] = []
    _write_json(root, gold_path, report)
    _refresh_evidence_hashes(root, document)

    release = _build(document, root)

    assert release["passed"] is False
    assert "gold_release_incomplete" in {
        failure["code"] for failure in release["failures"]
    }


def test_release_report_rejects_an_extra_failed_acceptance_evidence_file(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    row = document["acceptance_rows"][0]
    extra = "out/evidence/acceptance/base-01-hidden-failure.json"
    row["evidence_paths"].append(extra)
    _write_json(
        root,
        extra,
        {
            "schema_version": "1.0",
            "gate": row["id"],
            "passed": False,
        },
    )
    _refresh_evidence_hashes(root, document)

    release = _build(document, root)

    assert release["passed"] is False
    assert "acceptance_evidence_mismatch" in {
        failure["code"] for failure in release["failures"]
    }


def test_release_report_rejects_garbage_manifest_and_non_png_screenshots(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    gold_path = document["gold"]["evidence_path"]
    report = json.loads((root / gold_path).read_text(encoding="utf-8"))
    # Keep the source tree clean so this isolates GOLD's evidence validation;
    # source drift has its own fail-closed release test.
    manifest_path = "out/evidence/gold-01-garbage-manifest.json"
    report["manifest"]["path"] = manifest_path
    _write_json(root, manifest_path, {"garbage": True})
    report["manifest"]["sha256"] = hashlib.sha256(
        (root / manifest_path).read_bytes()
    ).hexdigest()
    first_screen = report["goldens"][0]["screenshots"][0]["path"]
    (root / first_screen).write_bytes(b"not a png")
    _write_json(root, gold_path, report)
    _refresh_evidence_hashes(root, document)

    release = _build(document, root)

    assert release["passed"] is False
    assert "gold_release_incomplete" in {
        failure["code"] for failure in release["failures"]
    }


def test_release_report_rejects_route_evidence_for_a_different_git_tree(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    relative = document["routing"]["evidence_path"]
    report = json.loads((root / relative).read_text(encoding="utf-8"))
    report["evaluation_provenance"]["head_tree_sha256"] = "f" * 64
    _write_json(root, relative, report)
    _refresh_evidence_hashes(root, document)

    release = _build(document, root)

    assert release["passed"] is False
    assert "routing_evidence_failed" in {
        failure["code"] for failure in release["failures"]
    }


def test_release_report_rejects_route_bytes_changed_after_bound_commit(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    relative = document["routing"]["evidence_path"]
    report = json.loads((root / relative).read_text(encoding="utf-8"))
    (root / relative).write_text(
        json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    _refresh_evidence_hashes(root, document)

    release = _build(document, root)

    assert release["passed"] is False
    assert "routing_evidence_failed" in {
        failure["code"] for failure in release["failures"]
    }


def test_release_report_accepts_route_measurement_from_unchanged_ancestor(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    route_relative = document["routing"]["evidence_path"]
    route = json.loads((root / route_relative).read_text(encoding="utf-8"))

    release = _build(document, root)

    assert route["evaluation_provenance"]["head_commit"] == document["commit"]
    assert _git(root, "rev-parse", "HEAD") != document["commit"]
    assert release["passed"] is True


def test_release_report_rejects_service_claims_without_operational_receipts(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    service = document["service"]
    health = {
        "schema_version": "1.0",
        "gate": "service",
        **{
            key: service[key]
            for key in ("commit", "passed", "active", "restarted_commit", "healthz_green")
        },
    }
    gallery = {
        "schema_version": "1.0",
        "gate": "service_gallery",
        "commit": service["commit"],
        "passed": True,
        "gallery_count": 6,
        "instant_gallery_passed": True,
        "generation_posts": 0,
        "external_requests": 0,
    }
    _write_json(root, service["health_evidence_path"], health)
    _write_json(root, service["gallery_evidence_path"], gallery)
    _refresh_evidence_hashes(root, document)

    release = _build(document, root)

    assert release["passed"] is False
    assert "service_not_green" in {
        failure["code"] for failure in release["failures"]
    }


def test_release_report_rejects_incompatible_static_asset_evidence(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    relative = document["asset"]["evidence_path"]
    evidence = json.loads((root / relative).read_text(encoding="utf-8"))
    evidence["bundle_sha256"] = "0" * 64
    _write_json(root, relative, evidence)
    _refresh_evidence_hashes(root, document)

    release = _build(document, root)

    assert release["passed"] is False
    assert "asset_contract_failed" in {
        failure["code"] for failure in release["failures"]
    }


def test_release_report_rejects_clean_checkout_without_archive_or_junit(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    clean = document["clean_checkout"]
    _write_json(
        root,
        clean["evidence_path"],
        {"schema_version": "1.0", "gate": "clean_checkout", **clean},
    )
    _refresh_evidence_hashes(root, document)

    release = _build(document, root)

    assert release["passed"] is False
    assert "clean_checkout_failed" in {
        failure["code"] for failure in release["failures"]
    }


def test_release_report_rejects_a_crc_corrupt_png_with_valid_signature(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    gold_relative = document["gold"]["evidence_path"]
    gold = json.loads((root / gold_relative).read_text(encoding="utf-8"))
    screenshot_relative = gold["goldens"][0]["screenshots"][0]["path"]
    screenshot = root / screenshot_relative
    corrupted = bytearray(screenshot.read_bytes())
    corrupted[-5] ^= 0x01
    screenshot.write_bytes(corrupted)
    digest = hashlib.sha256(corrupted).hexdigest()
    for golden in gold["goldens"]:
        for record in golden["screenshots"]:
            if record["path"] == screenshot_relative:
                record["sha256"] = digest
                record["expected_sha256"] = digest
        for locale in golden["locales"].values():
            for record in locale["screenshots"]:
                if record["path"] == screenshot_relative:
                    record["sha256"] = digest
                    record["expected_sha256"] = digest
    _write_json(root, gold_relative, gold)
    _refresh_evidence_hashes(root, document)

    release = _build(document, root)

    assert "gold_release_incomplete" in {
        failure["code"] for failure in release["failures"]
    }


def test_release_report_rejects_a_grayscale_png_with_an_illegal_palette(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    gold_relative = document["gold"]["evidence_path"]
    gold = json.loads((root / gold_relative).read_text(encoding="utf-8"))
    screenshot_relative = gold["goldens"][0]["screenshots"][0]["path"]
    grayscale_row = b"\x00\x80\x80"
    invalid_png = b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 0, 0, 0, 0)),
            _png_chunk(b"PLTE", b"\x00\x00\x00"),
            _png_chunk(b"IDAT", zlib.compress(grayscale_row * 2)),
            _png_chunk(b"IEND", b""),
        )
    )
    (root / screenshot_relative).write_bytes(invalid_png)
    digest = hashlib.sha256(invalid_png).hexdigest()
    for golden in gold["goldens"]:
        for record in golden["screenshots"]:
            if record["path"] == screenshot_relative:
                record["sha256"] = digest
                record["expected_sha256"] = digest
        for locale in golden["locales"].values():
            for record in locale["screenshots"]:
                if record["path"] == screenshot_relative:
                    record["sha256"] = digest
                    record["expected_sha256"] = digest
    _write_json(root, gold_relative, gold)
    _refresh_evidence_hashes(root, document)

    release = _build(document, root)

    assert "gold_release_incomplete" in {
        failure["code"] for failure in release["failures"]
    }


def test_release_report_rejects_service_summary_without_raw_receipts(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    service = document["service"]
    health = json.loads(
        (root / service["health_evidence_path"]).read_text(encoding="utf-8")
    )
    gallery = json.loads(
        (root / service["gallery_evidence_path"]).read_text(encoding="utf-8")
    )
    health.pop("commands")
    health.pop("http")
    gallery.pop("http")
    _write_json(root, service["health_evidence_path"], health)
    _write_json(root, service["gallery_evidence_path"], gallery)
    _refresh_evidence_hashes(root, document)

    release = _build(document, root)

    assert "service_not_green" in {
        failure["code"] for failure in release["failures"]
    }


def test_release_report_rejects_a_fabricated_clean_checkout_summary(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    clean = document["clean_checkout"]
    tree_sha256 = hashlib.sha256(
        _git(root, "rev-parse", f"{clean['commit']}^{{tree}}").encode()
    ).hexdigest()
    junit_relative = "out/evidence/release-clean-checkout.junit.xml"
    junit_path = root / junit_relative
    _write_json(
        root,
        clean["evidence_path"],
        {
            "schema_version": "1.0",
            "gate": "clean_checkout",
            **clean,
            "source": "git_archive",
            "source_tree_sha256": tree_sha256,
            "archive": {
                "kind": "git_archive",
                "commit": clean["commit"],
                "tree_sha256": tree_sha256,
                "tracked_status_clean": True,
            },
            "commands": ["pytest -q", "ruff check .", "git status --short"],
            "junit_path": junit_relative,
            "junit_sha256": hashlib.sha256(junit_path.read_bytes()).hexdigest(),
            "model_calls": 0,
        },
    )
    _refresh_evidence_hashes(root, document)

    release = _build(document, root)

    assert "clean_checkout_failed" in {
        failure["code"] for failure in release["failures"]
    }


def test_release_report_rejects_untracked_runtime_or_test_source(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    untracked = root / "server" / "untracked_runtime.py"
    untracked.parent.mkdir(parents=True, exist_ok=True)
    untracked.write_text("UNTRACKED = True\n", encoding="utf-8")

    with pytest.raises(ValueError, match="untracked source"):
        _build(document, root)


def test_release_report_rejects_an_untracked_runtime_claimed_as_evidence(
    release_case: tuple[Path, dict[str, object]],
):
    root, document = release_case
    untracked = root / "server" / "claimed_runtime_evidence.py"
    untracked.parent.mkdir(parents=True, exist_ok=True)
    untracked.write_text("UNTRACKED = True\n", encoding="utf-8")
    relative = untracked.relative_to(root).as_posix()
    document["evidence_sha256"][relative] = hashlib.sha256(
        untracked.read_bytes()
    ).hexdigest()

    with pytest.raises(ValueError, match="untracked source"):
        _build(document, root)
