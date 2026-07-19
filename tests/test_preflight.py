from __future__ import annotations

import json

from scripts.preflight import update_preflight


def test_preflight_recheck_preserves_model_smokes_and_records_primary_session(tmp_path):
    report_path = tmp_path / "preflight.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "sanitized": True,
                "competition": {"primary_build_thread": "pending"},
                "model_smokes": [{"model": "gpt-5.6-luna", "available": True}],
                "routing": {
                    "runtime_family_policy": "GPT-5.6 only",
                    "understand_model": "gpt-5.6-luna",
                    "understand_fallback_model": "gpt-5.6-sol",
                    "generate_model": "gpt-5.6-sol",
                    "heal_model": "gpt-5.6-sol",
                    "qa_model": "gpt-5.6-sol",
                },
                "release_confirmations": {},
            }
        ),
        encoding="utf-8",
    )

    updated = update_preflight(
        report_path,
        primary_session_id="019f7998-9378-72b2-b590-ee10e632ce81",
        environment_probe=lambda: {
            "python": "3.12.3",
            "node": "24.15.0",
            "browser_path": "/usr/bin/google-chrome",
            "disk_available_gib": 30,
        },
    )

    assert updated["sanitized"] is True
    assert updated["competition"]["primary_build_thread"] == (
        "019f7998-9378-72b2-b590-ee10e632ce81"
    )
    assert updated["model_smokes"] == [{"model": "gpt-5.6-luna", "available": True}]
    assert updated["release_confirmations"]["asset_licenses"] == (
        "MIT application code; GNU FreeFont under GPLv3+ with Font Exception"
    )


def test_preflight_refuses_non_gpt56_runtime_routing(tmp_path):
    report_path = tmp_path / "preflight.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "sanitized": True,
                "competition": {},
                "model_smokes": [],
                "routing": {
                    "runtime_family_policy": "GPT-5.6 only",
                    "understand_model": "not-permitted",
                },
                "release_confirmations": {},
            }
        ),
        encoding="utf-8",
    )

    try:
        update_preflight(report_path, primary_session_id="019f7998-9378-72b2-b590-ee10e632ce81")
    except ValueError as error:
        assert "GPT-5.6" in str(error)
    else:
        raise AssertionError("non-GPT-5.6 routing must fail preflight")
