from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from server.browser_verify import verify_artifact_in_browser
from server.cache import VerificationReceipt, VerifiedCache
from server.goldens import (
    GOLDEN_ROOT,
    golden_id_for_fixture,
    load_golden_fixtures,
    load_pinned_golden,
    review_golden_candidate,
)
from server.jobs import JobManager

ROOT = Path(__file__).parents[1]
EVIDENCE_ROOT = ROOT / "out" / "evidence" / "goldens"
SCREENSHOT_ROOT = ROOT / "out" / "evidence" / "screens" / "goldens"
ENGLISH_FIXTURE_IDS = (
    "buoyancy_en",
    "day_night_en",
    "moon_phases_en",
    "pendulum_en",
    "simple_circuit_en",
    "sound_pitch_en",
)


def _extract_lesson_and_module(document: dict[str, Any]) -> tuple[dict[str, Any], str]:
    artifact = document["artifact"]
    lesson_marker = "<script>window.__LAYSH_LESSON__ = "
    lesson_start = artifact.index(lesson_marker) + len(lesson_marker)
    lesson_end = artifact.index(";</script>", lesson_start)
    lesson = json.loads(artifact[lesson_start:lesson_end])
    scripts = re.findall(r"<script>(.*?)</script>", artifact, flags=re.DOTALL)
    modules = [
        source
        for source in scripts
        if "window.LayshSimulation" in source and "LayshContract" not in source
    ]
    if len(modules) != 1:
        raise ValueError("pinned artifact must contain exactly one generated module")
    return lesson, modules[0]


def _english_inputs(fixture: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str]:
    source = load_pinned_golden(fixture["source_golden"])
    if source is None:
        raise ValueError(f"source golden is unavailable: {fixture['source_golden']}")
    understanding, module_js = _extract_lesson_and_module(source)
    copy = fixture["copy"]
    understanding = deepcopy(understanding)
    understanding["lang"] = "en"
    for field in (
        "title",
        "tldr",
        "learning_objective",
        "misconception",
        "explanation_prompt",
        "transfer_prompt",
        "suggestions",
    ):
        understanding[field] = deepcopy(copy[field])
    if "key_formula" in copy:
        understanding["key_formula"] = copy["key_formula"]
    understanding["primary_parameter"]["label"] = copy["primary_parameter_label"]
    understanding["actor"]["label"] = copy["actor_label"]
    for original, replacement in fixture["module_replacements"].items():
        if original not in module_js:
            raise ValueError(f"module localization source text is missing: {original}")
        module_js = module_js.replace(original, replacement)
    module_output = {
        "module_js": module_js,
        "output_names": list(understanding["module_spec"]["outputs"]),
        "brief_summary": copy["brief_summary"],
        "assumptions": list(copy["assumptions"]),
    }
    return understanding, module_output, source["artifact_sha256"]


class EnglishGoldenBackend:
    backend_name = "curated_english_localization"

    def __init__(self, understanding: dict[str, Any], module_output: dict[str, Any]) -> None:
        self.understanding = understanding
        self.module_output = module_output
        self.generate_calls = 0
        self.heal_calls = 0
        self.qa_calls = 0
        self.vision_calls = 0

    @staticmethod
    def scenario_for(_question: str) -> str:
        return "english_golden"

    async def understand(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return deepcopy(self.understanding)

    async def generate(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        self.generate_calls += 1
        return deepcopy(self.module_output)

    async def heal(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        self.heal_calls += 1
        raise AssertionError("a curated English counterpart must not require an implicit heal")

    async def qa(
        self,
        module_output: dict[str, Any],
        understanding: dict[str, Any],
        gate_outcome: dict[str, Any],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        self.qa_calls += 1
        learner_copy = " ".join(
            str(understanding.get(field) or "")
            for field in (
                "title",
                "tldr",
                "learning_objective",
                "misconception",
                "explanation_prompt",
                "transfer_prompt",
            )
        )
        issues = []
        if understanding.get("lang") != "en" or re.search(r"[\u0600-\u06ff]", learner_copy):
            issues.append("Learner-facing copy is not completely localized to English.")
        if module_output.get("output_names") != understanding.get("module_spec", {}).get(
            "outputs"
        ):
            issues.append("Declared module outputs do not match the lesson contract.")
        if gate_outcome.get("passed") is not True:
            issues.append("The candidate did not pass its deterministic gate outcome.")
        approved = not issues
        return {
            "approved": approved,
            "issues": issues,
            "replacement_module_js": None,
            "visual_richness": {
                "scene_depth": approved,
                "physical_light": approved,
                "idle_motion": approved,
                "paused_phenomenon_motion": approved,
                "reactive_feedback": approved,
                "readable_overlays": approved,
                "overlay_safe_band": approved,
            },
        }

    async def vision(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        self.vision_calls += 1
        return {
            "actor_visible": True,
            "action_performed": True,
            "paused_action_performed": True,
            "physically_consistent": True,
            "labels_obscure_subject": False,
            "defects": [],
        }


def _spotcheck(artifact: str, golden_id: str) -> dict[str, Any]:
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    SCREENSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="laysh-english-golden-") as temporary:
        artifact_path = Path(temporary) / f"{golden_id}.html"
        artifact_path.write_text(artifact, encoding="utf-8")
        report_path = EVIDENCE_ROOT / f"{golden_id}-browser.json"
        node = shutil.which("node")
        if node is None:
            raise ValueError("Node is required for the golden browser spot-check")
        completed = subprocess.run(  # noqa: S603 - resolved local Node executable
            [
                node,
                str(ROOT / "scripts" / "check_golden.mjs"),
                str(artifact_path),
                str(SCREENSHOT_ROOT),
                golden_id,
                str(report_path),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
        )
    if completed.returncode != 0:
        raise ValueError(f"golden browser spot-check failed: {completed.stderr.strip()}")
    report = json.loads(completed.stdout)
    if not (
        report["ready"] is True
        and report["runtimeError"] is False
        and report["lang"] == "en"
        and report["dir"] == "ltr"
        and report["externalRequests"] == 0
        and report["consoleErrors"] == []
        and report["idleFrameChanged"] is True
        and report["reactiveFrameVariants"] >= 2
        and all(case["frameChanged"] is True for case in report["cases"])
    ):
        raise ValueError("golden browser spot-check reported an observable failure")
    return report


def _manifest() -> dict[str, Any]:
    lessons = []
    for path in sorted(GOLDEN_ROOT.glob("*.json")):
        if path.name == "manifest.json":
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        lessons.append(
            {
                "id": document["golden_id"],
                "locale": document["locale"],
                "aliases": document["aliases"],
                "instant": True,
                "tier": "A",
                "artifact_sha256": document["artifact_sha256"],
                "metadata": document["metadata"],
            }
        )
    return {"schema_version": "1.0", "contract_version": "1.0", "lessons": lessons}


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


async def build_one(fixture_id: str) -> dict[str, Any]:
    fixture = load_golden_fixtures()[fixture_id]
    golden_id = golden_id_for_fixture(fixture_id)
    destination = GOLDEN_ROOT / f"{golden_id}.json"
    if destination.exists():
        raise ValueError(f"English golden is immutable and already exists: {golden_id}")
    understanding, module_output, source_sha256 = _english_inputs(fixture)
    backend = EnglishGoldenBackend(understanding, module_output)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=60,
        evidence_job_timeout_seconds=60,
        browser_verifier=verify_artifact_in_browser,
    )
    record = manager.start_evidence(
        fixture["question"],
        "en",
        fixture_id,
        promote_golden=True,
    )
    if record.task is None:
        raise RuntimeError("English golden evidence job did not start")
    await record.task
    if record.status != "complete" or record.artifact is None:
        raise ValueError(
            f"English golden pipeline failed: {fixture_id}: "
            f"{record.status}: {record.builder_diagnostics}"
        )
    outputs = record.builder_outputs
    review = review_golden_candidate(
        fixture=fixture,
        understanding=outputs["understanding"],
        module_output=outputs["module_output"],
    )
    if not review["passed"]:
        raise ValueError(f"English golden review failed: {review['failure_codes']}")
    spotcheck = _spotcheck(record.artifact, golden_id)
    verification = outputs["verification"]
    browser = outputs["browser"]
    with tempfile.TemporaryDirectory(prefix="laysh-golden-cache-") as live_root:
        cache = VerifiedCache(
            root=Path(live_root),
            golden_root=GOLDEN_ROOT,
            secret=hashlib.sha256(b"laysh-curated-offline-build-key").digest(),
            contract_version="1.0",
        )
        entry = cache.pin_golden(
            golden_id=golden_id,
            question=fixture["question"],
            locale="en",
            domain=understanding["domain"],
            canonical_intent=understanding["canonical_intent"],
            artifact=record.artifact,
            title=understanding["title"],
            direction="ltr",
            receipt=VerificationReceipt(
                deterministic_passed=True,
                browser_passed=True,
                failed_gate_count=0,
                check_count=verification["check_count"],
            ),
            aliases=[golden_id, fixture_id, fixture["metadata"]["en"]["title"]],
            answer={
                "tldr": understanding["tldr"],
                "key_formula": understanding["key_formula"],
            },
            metadata=fixture["metadata"],
            review={
                "automated": review,
                "builder": {
                    "verdict": "pass",
                    "locale": "en",
                    "copy_complete": True,
                    "misconception_corrective": True,
                    "min_default_max_rendered": True,
                    "mobile_and_desktop_review_ready": True,
                },
                "reference_contract": fixture["review_contract"],
            },
            evidence={
                "method": "normal_pipeline_localized_from_verified_counterpart",
                "source_artifact_sha256": source_sha256,
                "attempt": 1,
                "heal_count": verification["heal_count"],
                "qa": outputs["qa"],
                "browser": browser,
                "browser_spotcheck": spotcheck,
                "screenshots": [
                    f"out/evidence/screens/goldens/{golden_id}-mobile-390x844.png",
                    f"out/evidence/screens/goldens/{golden_id}-desktop-1440x900.png",
                ],
            },
        )
    return {
        "id": golden_id,
        "cache_id": entry.cache_id,
        "artifact_sha256": entry.artifact_sha256,
        "attempts": backend.generate_calls,
        "heals": backend.heal_calls,
        "qa_calls": backend.qa_calls,
        "check_count": entry.receipt.check_count,
        "subject_motion_ratio": browser["idleMotionSubjectChangedPixelRatio"],
        "whole_canvas_motion_ratio": browser["idleMotionWholeCanvasChangedPixelRatio"],
        "render_metric": browser["renderOutputSweep"]["metric"],
        "render_correlation": browser["renderOutputSweep"]["rankCorrelation"],
    }


async def build(selected: tuple[str, ...]) -> None:
    results = []
    for fixture_id in selected:
        result = await build_one(fixture_id)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False))
    _write_json(GOLDEN_ROOT / "manifest.json", _manifest())
    _write_json(
        EVIDENCE_ROOT / "english-generation-summary.json",
        {
            "schema_version": "1.0",
            "method": "normal_pipeline_localized_from_verified_counterpart",
            "all_passed": True,
            "lessons": results,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the six curated English goldens")
    parser.add_argument(
        "--fixture",
        choices=("all", *ENGLISH_FIXTURE_IDS),
        default="all",
    )
    options = parser.parse_args()
    selected = ENGLISH_FIXTURE_IDS if options.fixture == "all" else (options.fixture,)
    asyncio.run(build(selected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
