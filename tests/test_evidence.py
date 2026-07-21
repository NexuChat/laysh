from types import SimpleNamespace


def test_g2_evidence_contains_stage_receipts_without_raw_question():
    from server.evidence import build_g2_evidence

    record = SimpleNamespace(
        job_id="job_safe",
        question="PRIVATE-QUESTION",
        status="complete",
        stage_executions=[
            {
                "stage": "understand",
                "attempt": 1,
                "model": "gpt-5.6-luna",
                "outcome": "failed",
                "elapsed_ms": None,
                "failure_code": "stage_timeout",
                "thread_id": None,
            },
            {
                "stage": "understand",
                "attempt": 2,
                "model": "gpt-5.6-sol",
                "outcome": "completed",
                "elapsed_ms": 4200,
                "failure_code": None,
                "thread_id": "thread-generate",
            },
        ],
        state_history=["queued", "filtering", "understanding", "answered", "complete"],
        events=[SimpleNamespace(type="answer"), SimpleNamespace(type="result")],
        simulation=SimpleNamespace(
            sim_id="sim_123",
            effective_model="gpt-5.6-sol",
            elapsed_ms=5500,
            check_count=7,
            heal_count=0,
        ),
        fallback=None,
    )
    evidence = build_g2_evidence(
        record=record,
        artifact_sha256="abc123",
        browser_evidence={"ready": True, "externalRequests": 0},
        total_elapsed_ms=5600,
    )

    assert evidence["runtime_family"] == "GPT-5.6"
    assert evidence["stages"] == [
        {
            "stage": "understand",
            "attempt": 1,
            "model": "gpt-5.6-luna",
            "outcome": "failed",
            "elapsed_ms": None,
            "failure_code": "stage_timeout",
            "thread_id": None,
            "evidence_mode": True,
        },
        {
            "stage": "understand",
            "attempt": 2,
            "model": "gpt-5.6-sol",
            "outcome": "completed",
            "elapsed_ms": 4200,
            "failure_code": None,
            "thread_id": "thread-generate",
            "evidence_mode": True,
        },
    ]
    assert "PRIVATE-QUESTION" not in str(evidence)
    assert "question" not in evidence
