from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from server.codex_runtime import CodexExecutor
from server.schema_acceptance import (
    OUTPUT_SCHEMA_PROBES,
    SCHEMA_ACCEPTANCE_FIXTURE_ID,
    SCHEMA_ACCEPTANCE_MODEL,
    run_schema_probes,
)
from server.settings import Settings

ROOT = Path(__file__).parents[1]
REPORT_PATH = ROOT / "out" / "evidence" / "schema-acceptance.json"
DIAGNOSTIC_PATH = ROOT / "out" / "evidence" / "schema-acceptance-diagnostic.json"


def atomic_write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_report() -> dict[str, Any]:
    if not REPORT_PATH.exists():
        return {
            "contract_version": "1.0",
            "model": SCHEMA_ACCEPTANCE_MODEL,
            "schemas": {},
            "all_accepted": False,
        }
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


async def run(selected: tuple[str, ...], *, force: bool) -> int:
    report = load_report()
    pending = selected
    if not force:
        pending = tuple(
            name
            for name in selected
            if not report.get("schemas", {}).get(name, {}).get("accepted", False)
        )
    settings = Settings.from_env()
    executor = CodexExecutor(
        stage_timeout_seconds=settings.public_stage_timeout_seconds,
        evidence_stage_timeout_seconds=settings.evidence_stage_timeout_seconds,
        record_runtime=True,
        evidence_allowlist=frozenset({SCHEMA_ACCEPTANCE_FIXTURE_ID}),
    )
    outcomes = await run_schema_probes(executor, pending)
    diagnostics: dict[str, Any] = {"model": SCHEMA_ACCEPTANCE_MODEL, "schemas": {}}

    for name, outcome in outcomes.items():
        entry = report.setdefault("schemas", {}).setdefault(name, {"attempts": []})
        attempt = outcome.public_dict()
        attempt["attempt"] = len(entry["attempts"]) + 1
        entry["attempts"].append(attempt)
        entry["accepted"] = outcome.accepted
        if outcome.builder_detail:
            diagnostics["schemas"][name] = {
                "attempt": attempt["attempt"],
                "error_code": outcome.error_code,
                "builder_detail": outcome.builder_detail,
            }

    report["model"] = SCHEMA_ACCEPTANCE_MODEL
    report["all_accepted"] = all(
        report.get("schemas", {}).get(name, {}).get("accepted", False)
        for name in OUTPUT_SCHEMA_PROBES
    )
    atomic_write(REPORT_PATH, report)
    if diagnostics["schemas"]:
        atomic_write(DIAGNOSTIC_PATH, diagnostics)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["all_accepted"] else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe Codex output-schema acceptance on Luna")
    parser.add_argument("--schema", action="append", choices=tuple(OUTPUT_SCHEMA_PROBES))
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    names = tuple(arguments.schema or OUTPUT_SCHEMA_PROBES)
    sys.exit(asyncio.run(run(names, force=arguments.force)))
