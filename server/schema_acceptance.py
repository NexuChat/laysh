from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any

from server.codex_backend import CODEX_OUTPUT_SCHEMA_BY_STAGE
from server.codex_runtime import CodexRuntimeError

SCHEMA_ACCEPTANCE_MODEL = "gpt-5.6-luna"
SCHEMA_ACCEPTANCE_FIXTURE_ID = "schema_acceptance"

OUTPUT_SCHEMA_PROBES: dict[str, tuple[str, dict[str, Any]]] = {
    "understand": (
        "understand",
        {
            "safe": True,
            "unsafe_category": None,
            "simulatable": False,
            "reason_code": "schema_probe",
            "lang": "en",
            "canonical_intent": "schema_probe",
            "domain": "science",
            "title": "Schema probe",
            "tldr": "A minimal structured-output contract probe.",
            "key_formula": None,
            "learning_objective": "Confirm schema acceptance.",
            "primary_parameter": None,
            "secondary_parameter": None,
            "prediction": None,
            "misconception": None,
            "explanation_prompt": None,
            "transfer_prompt": None,
            "module_spec": {"outputs": []},
            "checks": [],
            "suggestions": [],
        },
    ),
    "module": (
        "generate",
        {
            "module_js": "window.LayshSimulation = {};",
            "output_names": ["probe"],
            "brief_summary": "Schema acceptance probe.",
            "assumptions": [],
        },
    ),
    "qa": (
        "qa",
        {
            "approved": True,
            "issues": [],
            "replacement_module_js": None,
            "visual_richness": {
                "scene_depth": True,
                "physical_light": True,
                "idle_motion": True,
                "reactive_feedback": True,
                "readable_overlays": True,
            },
        },
    ),
}


@dataclass(frozen=True, slots=True)
class SchemaProbeOutcome:
    schema: str
    accepted: bool
    model: str
    elapsed_ms: int
    thread_id: str | None = None
    error_code: str | None = None
    builder_detail: str | None = None

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("builder_detail")
        return value


async def run_schema_probes(
    executor: Any,
    schema_names: tuple[str, ...] | None = None,
) -> dict[str, SchemaProbeOutcome]:
    selected = schema_names or tuple(OUTPUT_SCHEMA_PROBES)
    outcomes: dict[str, SchemaProbeOutcome] = {}
    for schema_name in selected:
        stage, exact_object = OUTPUT_SCHEMA_PROBES[schema_name]
        prompt = (
            "Return a valid object matching the supplied output schema. "
            "Return this exact object and no commentary: "
            + json.dumps(exact_object, ensure_ascii=False, separators=(",", ":"))
        )
        started = time.monotonic()
        try:
            result = await executor.execute_stage(
                prompt=prompt,
                schema_path=CODEX_OUTPUT_SCHEMA_BY_STAGE[stage],
                model=SCHEMA_ACCEPTANCE_MODEL,
                effort="low",
                public=False,
                evidence_fixture_id=SCHEMA_ACCEPTANCE_FIXTURE_ID,
            )
        except CodexRuntimeError as error:
            outcomes[schema_name] = SchemaProbeOutcome(
                schema=schema_name,
                accepted=False,
                model=SCHEMA_ACCEPTANCE_MODEL,
                elapsed_ms=max(0, int((time.monotonic() - started) * 1000)),
                error_code=error.code,
                builder_detail=error.builder_detail,
            )
        else:
            outcomes[schema_name] = SchemaProbeOutcome(
                schema=schema_name,
                accepted=True,
                model=result.model,
                elapsed_ms=result.elapsed_ms,
                thread_id=result.thread_id,
            )
    return outcomes
