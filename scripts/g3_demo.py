from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import tempfile
from dataclasses import asdict
from pathlib import Path

from server.browser_verify import verify_artifact_in_browser
from server.cache import VerifiedCache
from server.codex_backend import MockCodexBackend
from server.jobs import JobManager

ROOT = Path(__file__).parents[1]


async def run_demo(cache_parent: Path) -> dict:
    browser_reports = []

    def recorded_browser_verifier(artifact: str):
        result = verify_artifact_in_browser(artifact)
        browser_reports.append(result)
        return result

    cache = VerifiedCache(
        root=cache_parent / "live",
        golden_root=cache_parent / "golden",
        secret=b"g3-repeatable-offline-fixture-secret",
        contract_version="1.0",
    )
    backend = MockCodexBackend()
    manager = JobManager(
        backend,
        public_job_timeout_seconds=30,
        evidence_job_timeout_seconds=30,
        browser_verifier=recorded_browser_verifier,
        cache=cache,
    )
    record = manager.start_evidence("broken first draft", "ar", "moon_phases_ar")
    if record.task is None:
        raise RuntimeError("G3 demo did not start")
    await record.task
    entries = cache.list_entries()
    simulation = record.simulation
    browser = browser_reports[-1] if browser_reports else None
    state_history = list(record.state_history)
    verify_positions = [
        index for index, state in enumerate(state_history) if state == "verifying"
    ]
    heal_position = state_history.index("healing") if "healing" in state_history else -1
    verify_heal_reverify = (
        len(verify_positions) >= 2
        and verify_positions[0] < heal_position < verify_positions[-1]
    )
    cache_evidence = {
        "entry_count": len(entries),
        "cache_id": entries[0].cache_id if entries else None,
        "artifact_sha256": entries[0].artifact_sha256 if entries else None,
        "receipt": asdict(entries[0].receipt) if entries else None,
    }
    artifact_sha256 = (
        hashlib.sha256(record.artifact.encode()).hexdigest() if record.artifact else None
    )
    gate_g3_passed = bool(
        record.status == "complete"
        and simulation is not None
        and simulation.heal_count == 1
        and verify_heal_reverify
        and browser is not None
        and browser.passed
        and len(entries) == 1
        and entries[0].receipt.verified
        and entries[0].artifact_sha256 == artifact_sha256
    )
    return {
        "schema_version": "1.0",
        "fixture_id": "broken_first_draft_offline",
        "status": record.status,
        "state_history": state_history,
        "heal_count": simulation.heal_count if simulation else None,
        "verify_heal_reverify": verify_heal_reverify,
        "heal_received_failures": (
            backend.last_heal_failures[0] if backend.last_heal_failures else []
        ),
        "browser": browser.evidence if browser else None,
        "artifact_sha256": artifact_sha256,
        "cache": cache_evidence,
        "gate_g3_passed": gate_g3_passed,
    }


async def async_main(output: Path) -> int:
    with tempfile.TemporaryDirectory(prefix="laysh-g3-demo-") as temporary:
        evidence = await run_demo(Path(temporary) / "cache")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(output.suffix + ".tmp")
    temporary_output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_output.replace(output)
    print(json.dumps(evidence, ensure_ascii=False))
    return 0 if evidence["gate_g3_passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the repeatable offline Laysh G3 demo")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "out" / "evidence" / "g3-heal-demo.json",
    )
    arguments = parser.parse_args()
    return asyncio.run(async_main(arguments.output))


if __name__ == "__main__":
    raise SystemExit(main())
