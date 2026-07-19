from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from server.codex_runtime import CodexExecutor, StageExecution
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
        return await self.executor.execute_stage(
            prompt=self._render_prompt(
                "understand.md",
                {"question": question, "locale": locale},
            ),
            schema_path=CODEX_OUTPUT_SCHEMA_BY_STAGE["understand"],
            model=self.settings.understand_model,
            effort="low",
            **self._execution_policy(runtime_context),
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
        failures: list[str],
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
        *,
        runtime_context: RuntimeContext | None = None,
    ) -> StageExecution:
        return await self.executor.execute_stage(
            prompt=self._render_prompt(
                "qa.md",
                {"module_output": module_output, "understanding": understanding},
            ),
            schema_path=CODEX_OUTPUT_SCHEMA_BY_STAGE["qa"],
            model=self.settings.qa_model,
            effort="medium",
            **self._execution_policy(runtime_context),
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
        "key_formula": "f = (1 - cos θ) / 2",
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
            "ظل الأرض هو سبب أطوار القمر"
            if arabic
            else "Earth's shadow causes the Moon's phases"
        ),
        "explanation_prompt": (
            "تغيّر الجزء المضيء لأن…" if arabic else "The lit part changed because…"
        ),
        "transfer_prompt": (
            "ماذا تتوقع عند زاوية 180°؟" if arabic else "What do you expect at 180°?"
        ),
        "module_spec": {"outputs": ["lit_fraction"]},
        "checks": [
            {
                "id": "quarter_phase",
                "kind": "numeric",
                "inputs": {"angle_deg": 90},
                "output": "lit_fraction",
                "expected": 0.5,
                "tolerance": 0.02,
                "unit": "ratio",
            },
            {
                "id": "full_phase",
                "kind": "numeric",
                "inputs": {"angle_deg": 180},
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
            "module_spec": {"outputs": []},
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
            "module_spec": {"outputs": []},
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
        failures: list[str],
        attempt: int,
        *,
        runtime_context: RuntimeContext | None = None,
    ) -> dict[str, Any]:
        del failures, attempt, runtime_context
        self.heal_calls += 1
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
        *,
        runtime_context: RuntimeContext | None = None,
    ) -> dict[str, Any]:
        del module_output, understanding, runtime_context
        self.qa_calls += 1
        return {"approved": True, "issues": [], "replacement_module_js": None}

    @staticmethod
    def scenario_for_source(source: str) -> str:
        return "exhausted" if "EXHAUSTED_HEAL" in source else "repairable"

    def mark_exhausted(self, module_output: dict[str, Any]) -> dict[str, Any]:
        value = deepcopy(module_output)
        value["module_js"] = "window.LayshSimulation = {}; fetch('/EXHAUSTED_HEAL');"
        return value
