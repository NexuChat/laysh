from __future__ import annotations

import asyncio
import json
import logging
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from server.codex_runtime import CodexExecutor, CodexPolicyError, CodexRuntimeError, StageExecution
from server.schemas import validate_module_output, validate_understanding
from server.settings import Settings

ROOT = Path(__file__).parents[1]
PROMPT_DIR = Path(__file__).parent / "prompts"
SCHEMA_DIR = Path(__file__).parent / "schemas"
CODEX_OUTPUT_SCHEMA_BY_STAGE = {
    "understand": SCHEMA_DIR / "understand.schema.json",
    "generate": SCHEMA_DIR / "module.schema.json",
    "heal": SCHEMA_DIR / "module.schema.json",
    "qa": SCHEMA_DIR / "qa.schema.json",
}
CODEX_OUTPUT_SCHEMAS = tuple(sorted(set(CODEX_OUTPUT_SCHEMA_BY_STAGE.values())))
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    public: bool = True
    evidence_fixture_id: str | None = None


class CodexBackend:
    """Structured GPT-5.6-only stage backend."""

    backend_name = "codex"

    def __init__(self, *, executor: CodexExecutor, settings: Settings) -> None:
        self.executor = executor
        self.settings = settings

    @staticmethod
    def _render_prompt(name: str, payload: dict[str, Any]) -> str:
        template = (PROMPT_DIR / name).read_text(encoding="utf-8")
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return template.replace("@@INPUT_JSON@@", serialized)

    @staticmethod
    def _execution_policy(context: RuntimeContext | None) -> dict[str, Any]:
        selected = context or RuntimeContext()
        return {
            "public": selected.public,
            "evidence_fixture_id": selected.evidence_fixture_id,
        }

    async def understand(
        self,
        question: str,
        locale: str | None,
        *,
        runtime_context: RuntimeContext | None = None,
    ) -> StageExecution:
        selected_context = runtime_context or RuntimeContext()
        model = (
            self.settings.understand_model
            if selected_context.public
            else self.settings.evidence_understand_model
        )
        input_payload: dict[str, Any] = {"question": question, "locale": locale}
        if not selected_context.public and selected_context.evidence_fixture_id:
            from server.goldens import load_golden_fixtures

            fixture = load_golden_fixtures().get(selected_context.evidence_fixture_id)
            if fixture is not None:
                input_payload["builder_reference_contract"] = fixture["review_contract"]
        prompt = self._render_prompt("understand.md", input_payload)
        policy = self._execution_policy(selected_context)
        started = time.monotonic()
        try:
            return await self.executor.execute_stage(
                prompt=prompt,
                schema_path=CODEX_OUTPUT_SCHEMA_BY_STAGE["understand"],
                model=model,
                effort="low",
                **policy,
            )
        except CodexPolicyError:
            raise
        except CodexRuntimeError as error:
            fallback = self.settings.understand_fallback_model
            if not selected_context.public or fallback == model:
                raise
            failure_code = error.code
            LOGGER.warning(
                "public understand retry: primary_model=%s failure=%s upstream_kind=%s "
                "upstream_code=%s fallback_model=%s",
                model,
                error.code,
                error.safe_detail.get("kind"),
                error.safe_detail.get("code"),
                fallback,
            )
        result = await self.executor.execute_stage(
            prompt=prompt,
            schema_path=CODEX_OUTPUT_SCHEMA_BY_STAGE["understand"],
            model=fallback,
            effort="low",
            **policy,
        )
        return StageExecution(
            data=result.data,
            thread_id=result.thread_id,
            model=result.model,
            elapsed_ms=max(result.elapsed_ms, int((time.monotonic() - started) * 1000)),
            attempted_models=(model, fallback),
            prior_failure_codes=(failure_code,),
        )

    async def generate(
        self,
        understanding: dict[str, Any],
        scenario: str = "live",
        *,
        runtime_context: RuntimeContext | None = None,
    ) -> StageExecution:
        del scenario
        return await self.executor.execute_stage(
            prompt=self._render_prompt("generate_module.md", understanding),
            schema_path=CODEX_OUTPUT_SCHEMA_BY_STAGE["generate"],
            model=self.settings.generate_model,
            effort="medium",
            **self._execution_policy(runtime_context),
        )

    async def heal(
        self,
        module_output: dict[str, Any],
        understanding: dict[str, Any],
        failures: list[dict[str, Any]],
        attempt: int,
        *,
        runtime_context: RuntimeContext | None = None,
    ) -> StageExecution:
        return await self.executor.execute_stage(
            prompt=self._render_prompt(
                "heal_module.md",
                {
                    "module_output": module_output,
                    "understanding": understanding,
                    "exact_gate_failures": failures,
                    "attempt": attempt,
                },
            ),
            schema_path=CODEX_OUTPUT_SCHEMA_BY_STAGE["heal"],
            model=self.settings.heal_model,
            effort="high" if attempt == 2 else "medium",
            **self._execution_policy(runtime_context),
        )

    async def qa(
        self,
        module_output: dict[str, Any],
        understanding: dict[str, Any],
        gate_outcome: dict[str, Any],
        *,
        runtime_context: RuntimeContext | None = None,
    ) -> StageExecution:
        selected_context = runtime_context or RuntimeContext()
        return await self.executor.execute_stage(
            prompt=self._render_prompt(
                "qa.md",
                {
                    "module_source": module_output["module_js"],
                    "module_spec": understanding["module_spec"],
                    "fixtures": understanding["checks"],
                    "gate_outcome": gate_outcome,
                },
            ),
            schema_path=CODEX_OUTPUT_SCHEMA_BY_STAGE["qa"],
            model=self.settings.qa_model,
            effort="medium",
            timeout_seconds=(
                self.settings.public_qa_timeout_seconds
                if selected_context.public
                else self.settings.evidence_qa_timeout_seconds
            ),
            **self._execution_policy(selected_context),
        )


def _success_understanding(locale: str) -> dict[str, Any]:
    arabic = locale != "en"
    value = {
        "safe": True,
        "unsafe_category": None,
        "simulatable": True,
        "reason_code": "ok",
        "lang": "ar" if arabic else "en",
        "canonical_intent": "moon_phase_lit_fraction",
        "domain": "astronomy",
        "title": "لماذا يتغير شكل القمر؟" if arabic else "Why does the Moon change shape?",
        "tldr": (
            "يتغير الجزء المضيء الذي نراه لأن موضع القمر يتغير بالنسبة إلى الأرض والشمس."
            if arabic
            else "The lit part we see changes as the Moon moves relative to Earth and the Sun."
        ),
        "key_formula": "f = (1 − cos θ) / 2",
        "learning_objective": (
            "ربط زاوية المدار بالجزء المضيء المرئي"
            if arabic
            else "Connect orbital angle to the visible lit fraction"
        ),
        "primary_parameter": {
            "id": "angle_deg",
            "label": "زاوية القمر" if arabic else "Moon angle",
            "unit": "°",
            "min": 0,
            "max": 360,
            "default": 90,
            "step": 1,
        },
        "secondary_parameter": None,
        "prediction": {
            "prompt": (
                "عند زيادة الزاوية، هل يكبر الجزء المضيء أولًا؟"
                if arabic
                else "As the angle increases, does the lit part grow at first?"
            ),
            "choices": ["نعم", "لا"] if arabic else ["Yes", "No"],
        },
        "misconception": (
            "تصحيح: أطوار القمر تنتج من زاوية الشمس والأرض والقمر، لا من ظل الأرض."
            if arabic
            else "Correction: Moon phases come from the Sun-Earth-Moon angle, not Earth's shadow."
        ),
        "explanation_prompt": (
            "تغيّر الجزء المضيء لأن…" if arabic else "The lit part changed because…"
        ),
        "transfer_prompt": (
            "ماذا تتوقع عند زاوية 180°؟" if arabic else "What do you expect at 180°?"
        ),
        "module_spec": {"outputs": ["lit_fraction"], "actor": "moon", "action": "orbits"},
        "checks": [
            {
                "id": "quarter_phase",
                "kind": "numeric",
                "inputs": [{"name": "angle_deg", "value": 90}],
                "output": "lit_fraction",
                "expected": 0.5,
                "tolerance": 0.02,
                "unit": "ratio",
            },
            {
                "id": "full_phase",
                "kind": "numeric",
                "inputs": [{"name": "angle_deg", "value": 180}],
                "output": "lit_fraction",
                "expected": 1.0,
                "tolerance": 0.02,
                "unit": "ratio",
            },
        ],
        "suggestions": [],
    }
    return validate_understanding(value)


def _non_simulatable(locale: str) -> dict[str, Any]:
    arabic = locale != "en"
    return validate_understanding(
        {
            "safe": True,
            "unsafe_category": None,
            "simulatable": False,
            "reason_code": "not_simulatable",
            "lang": "ar" if arabic else "en",
            "canonical_intent": "open_ended_science_explanation",
            "domain": "science",
            "title": "جواب علمي موجز" if arabic else "A concise science answer",
            "tldr": (
                "يمكن شرح الفكرة بوضوح، لكن لا يوجد متغيّر واحد يمكن نمذجته هنا بأمان."
                if arabic
                else (
                    "The idea can be explained clearly, but it has no single variable "
                    "we can model honestly."
                )
            ),
            "key_formula": None,
            "learning_objective": "تمييز الشرح عن النموذج القابل للقياس",
            "primary_parameter": None,
            "secondary_parameter": None,
            "prediction": None,
            "misconception": None,
            "explanation_prompt": None,
            "transfer_prompt": None,
            "module_spec": {"outputs": [], "actor": None, "action": None},
            "checks": [],
            "suggestions": [
                "لماذا يتغير شكل القمر؟",
                "كيف يؤثر طول البندول في زمنه؟",
                "لماذا تطفو بعض الأجسام؟",
            ],
        }
    )


def _unsafe(locale: str) -> dict[str, Any]:
    arabic = locale != "en"
    return validate_understanding(
        {
            "safe": False,
            "unsafe_category": "wrongdoing",
            "simulatable": False,
            "reason_code": "unsafe_redirect",
            "lang": "ar" if arabic else "en",
            "canonical_intent": "safe_science_redirect",
            "domain": "science",
            "title": (
                "لنستكشف سؤالًا علميًا آمنًا"
                if arabic
                else "Let's explore a safe science question"
            ),
            "tldr": "",
            "key_formula": None,
            "learning_objective": "الانتقال إلى استكشاف علمي آمن",
            "primary_parameter": None,
            "secondary_parameter": None,
            "prediction": None,
            "misconception": None,
            "explanation_prompt": None,
            "transfer_prompt": None,
            "module_spec": {"outputs": [], "actor": None, "action": None},
            "checks": [],
            "suggestions": [
                "لماذا يتغير شكل القمر؟",
                "كيف تعمل الدائرة الكهربائية البسيطة؟",
                "لماذا يتغير ارتفاع الصوت؟",
            ],
        }
    )


class MockCodexBackend:
    """Deterministic, quota-free stage backend for offline development and tests."""

    fixture_names = frozenset(
        {
            "success",
            "non_simulatable",
            "unsafe",
            "broken_first_draft",
            "exhausted_heal",
            "timeout",
        }
    )
    backend_name = "mock"

    def __init__(self) -> None:
        self.understand_calls = 0
        self.generate_calls = 0
        self.heal_calls = 0
        self.qa_calls = 0
        self.last_heal_failures: list[list[dict[str, Any]]] = []
        self._good_source = (ROOT / "tests" / "fixtures" / "moon_phase_module.js").read_text(
            encoding="utf-8"
        )

    def scenario_for(self, question: str) -> str:
        normalized = question.casefold()
        if "not simulatable" in normalized:
            return "non_simulatable"
        if "unsafe" in normalized:
            return "unsafe"
        if "broken first" in normalized:
            return "broken_first_draft"
        if "exhausted heal" in normalized:
            return "exhausted_heal"
        if "timeout" in normalized:
            return "timeout"
        return "success"

    def normalize_fixture(self, question: str) -> dict[str, Any]:
        english = question.casefold().startswith("why does")
        return _success_understanding("en" if english else "ar")

    async def understand(
        self,
        question: str,
        locale: str | None,
        *,
        runtime_context: RuntimeContext | None = None,
    ) -> dict[str, Any]:
        del runtime_context
        self.understand_calls += 1
        scenario = self.scenario_for(question)
        if scenario == "timeout":
            await asyncio.sleep(60)
        if scenario == "unsafe":
            return _unsafe(locale or "ar")
        if scenario == "non_simulatable":
            return _non_simulatable(locale or "ar")
        return deepcopy(_success_understanding(locale or "ar"))

    async def generate(
        self,
        understanding: dict[str, Any],
        scenario: str = "success",
        *,
        runtime_context: RuntimeContext | None = None,
    ) -> dict[str, Any]:
        del runtime_context
        self.generate_calls += 1
        source = self._good_source
        if scenario in {"broken_first_draft", "exhausted_heal"}:
            source = "window.LayshSimulation = {}; fetch('/forbidden');"
        return validate_module_output(
            {
                "module_js": source,
                "output_names": list(understanding["module_spec"]["outputs"]),
                "brief_summary": "وحدة أطوار قمر حتمية للاختبار دون اتصال.",
                "assumptions": ["مدار دائري مبسط", "لا تمثل المسافات بمقياس حقيقي"],
            }
        )

    async def heal(
        self,
        module_output: dict[str, Any],
        understanding: dict[str, Any],
        failures: list[dict[str, Any]],
        attempt: int,
        *,
        runtime_context: RuntimeContext | None = None,
    ) -> dict[str, Any]:
        del attempt, runtime_context
        self.heal_calls += 1
        self.last_heal_failures.append(deepcopy(failures))
        candidate = deepcopy(module_output)
        repairable = self.scenario_for_source(module_output["module_js"]) != "exhausted"
        if module_output["module_js"] and repairable:
            candidate["module_js"] = self._good_source
        candidate["output_names"] = list(understanding["module_spec"]["outputs"])
        return validate_module_output(candidate)

    async def qa(
        self,
        module_output: dict[str, Any],
        understanding: dict[str, Any],
        gate_outcome: dict[str, Any],
        *,
        runtime_context: RuntimeContext | None = None,
    ) -> dict[str, Any]:
        del module_output, understanding, gate_outcome, runtime_context
        self.qa_calls += 1
        return {
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
        }

    @staticmethod
    def scenario_for_source(source: str) -> str:
        return "exhausted" if "EXHAUSTED_HEAL" in source else "repairable"

    def mark_exhausted(self, module_output: dict[str, Any]) -> dict[str, Any]:
        value = deepcopy(module_output)
        value["module_js"] = "window.LayshSimulation = {}; fetch('/EXHAUSTED_HEAL');"
        return value
