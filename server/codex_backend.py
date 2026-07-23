from __future__ import annotations

import asyncio
import json
import logging
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from jsonschema import ValidationError

from server.codex_runtime import CodexExecutor, CodexPolicyError, CodexRuntimeError, StageExecution
from server.model_routing import ModelRoutingPolicy
from server.schemas import ContractError, validate_module_output, validate_understanding
from server.settings import ALLOWED_RUNTIME_MODELS, Settings

ROOT = Path(__file__).parents[1]
PROMPT_DIR = Path(__file__).parent / "prompts"
SCHEMA_DIR = Path(__file__).parent / "schemas"
CODEX_OUTPUT_SCHEMA_BY_STAGE = {
    "understand": SCHEMA_DIR / "understand.schema.json",
    "generate": SCHEMA_DIR / "module.schema.json",
    "generate_physics": SCHEMA_DIR / "physics_fragment.schema.json",
    "generate_visual": SCHEMA_DIR / "visual_fragment.schema.json",
    "heal": SCHEMA_DIR / "module.schema.json",
    "qa": SCHEMA_DIR / "qa.schema.json",
    "visual_qa": SCHEMA_DIR / "visual_qa.schema.json",
}
CODEX_OUTPUT_SCHEMAS = tuple(sorted(set(CODEX_OUTPUT_SCHEMA_BY_STAGE.values())))
LOGGER = logging.getLogger(__name__)

FRAGMENT_RETRY_HINTS: dict[str, str] = {
    "causal_scientific_actor_required": (
        "Set causal_response.actor_id to the primary scientific actor, not a "
        "decorative command or an unknown ID."
    ),
    "causal_output_undeclared": (
        "Set causal_response.output_name to one exact output declared by the fixed "
        "module spec; do not invent or rename outputs."
    ),
    "causal_fixture_required": (
        "Select a fixture-covered declared output for causal_response so its physics "
        "can be checked deterministically."
    ),
    "causal_channel_output_required": (
        "Make the causal actor field for the selected channel directly use "
        "output_<output_name>; normalized alone is not causal evidence."
    ),
    "signed_causal_fixture_coverage_required": (
        "Preserve distinct negative, zero, and positive actor behavior from the fixed "
        "signed output fixtures."
    ),
    "time_driven_scientific_motion_required": (
        "For time_driven motion, bind time and output_<declared_name> together in one "
        "salient scientific field; phase-only decoration does not qualify."
    ),
    "trajectory_output_undeclared": (
        "Set trajectory.output_name to one exact output declared by the fixed module "
        "spec; never invent a trajectory-only output alias."
    ),
    "unsupported_safety_envelope_relation": (
        "Use forbid contact and avoid scientific occlusion when a body group, vector, "
        "ray, or trajectory is represented by a conservative circular envelope."
    ),
    "representation_time_driven_deferred": (
        "Use parameter_driven or cyclic for representation.motion_model; time_driven "
        "requires phase A2 primitives and is not available yet."
    ),
    "representation_archetype_not_emittable": (
        "Choose body, elongated_body, orbital_pair, linked_bodies, or "
        "surface_and_body until the phase A2 command primitives are available."
    ),
    "representation_archetype_command_mismatch": (
        "Match actor_archetype to the emitted scientific circle and ellipse "
        "composition, including enough scientific actors for paired archetypes."
    ),
    "representation_actor_proof_unbacked": (
        "For every actor proof channel, make a scientific circle or ellipse field for "
        "that channel directly use output_<output_name>."
    ),
    "representation_graph_scene_required": (
        "Set representation.scene_pattern to world_plus_graph whenever graph is the "
        "selected proof medium."
    ),
    "representation_output_undeclared": (
        "Use an exact output declared by the fixed module spec for every "
        "representation proof channel; do not invent aliases."
    ),
    "scientific_output_reference_required": (
        "Every scientific circle or ellipse must visibly use output_<declared_name> "
        "in at least one geometry or opacity field. Fixed contextual shapes must set "
        "scientific false. Keep the causal actor bound through its declared channel."
    ),
    "undeclared_visual_output": (
        "Use only declared output names with the output_ prefix in visual expressions; "
        "remove invented output aliases."
    ),
    "undeclared_relation_output": (
        "Use only declared output names in relation expressions and keep relation "
        "geometry derived from the fixed visual commands."
    ),
    "scientific_relations_incomplete": (
        "Declare exactly one relation for every pair of scientific actors, with no "
        "missing or repeated pair."
    ),
    "scientific_relation_invalid": (
        "Each relation must name two unique scientific actor IDs that exist in the "
        "commands list."
    ),
    "duplicate_visual_command_id": (
        "Give every visual command a unique id and update causal_response and relation "
        "references to those exact IDs."
    ),
    "unsupported_scientific_geometry": (
        "Only a circle or ellipse may be scientific true; mark lines, arrows, waves, "
        "rectangles, and text as scientific false."
    ),
    "unsupported_ellipse_relation": (
        "Use one scientific ellipse for the primary actor and mark supporting pieces "
        "scientific false. Do not require contact or scientific occlusion for an ellipse."
    ),
    "scientific_salient_output_required": (
        "Make a declared output drive the scientific actor center, radius, rotation, "
        "or opacity; line width alone is not a visible response."
    ),
    "relation_clearance_invalid": (
        "Set minimum_clearance to zero whenever overlap is allowed or contact is "
        "required; otherwise use a nonnegative safe expression."
    ),
    "physics_output_contract_mismatch": (
        "Return the exact ordered output names from the fixed module spec and provide "
        "one matching physics expression for each."
    ),
    "duplicate_physics_output": (
        "Define each fixed output exactly once and keep expression names unique and in "
        "the module-spec order."
    ),
    "assembled_source_too_large": (
        "Reduce command count and text while preserving the primary scientific actor, "
        "causal response, and required relations."
    ),
    "undeclared_expression_name": (
        "Use only the exact declared parameter IDs and pi as names. Replace symbolic "
        "constants or aliases with finite numeric literals."
    ),
    "unsupported_expression_call": (
        "Use only the math calls listed in the fragment prompt and replace unsupported "
        "helpers with equivalent allowed arithmetic."
    ),
    "invalid_expression_arity": (
        "Call each allowed math function with its documented number of arguments."
    ),
    "fragment_schema_invalid": (
        "Return every field required by the closed role schema, no extra fields, and "
        "use the exact declared types and enum values."
    ),
    "fragment_semantic_validation_failed": (
        "Re-read the fixed role contract and return a fresh minimal fragment whose IDs, "
        "outputs, expressions, and relations are internally consistent."
    ),
}


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    public: bool = True
    evidence_fixture_id: str | None = None


@dataclass(frozen=True, slots=True)
class GenerationCandidateSpec:
    """Internal, closed routing decision for one independently verified candidate."""

    candidate_id: Literal["single", "fast", "quality"]
    ordinal: int
    model: Literal["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]
    effort: Literal["low", "medium", "high"]

    def __post_init__(self) -> None:
        if self.candidate_id not in {"single", "fast", "quality"}:
            raise ValueError("unknown generation candidate")
        if self.ordinal not in {1, 2}:
            raise ValueError("generation candidate ordinal must be one or two")
        if self.model not in ALLOWED_RUNTIME_MODELS:
            raise ValueError("generation candidate model must be GPT-5.6")
        if self.effort not in {"low", "medium", "high"}:
            raise ValueError("generation candidate effort is not allowed")


class CodexBackend:
    """Structured GPT-5.6-only stage backend."""

    backend_name = "codex"

    def __init__(
        self,
        *,
        executor: CodexExecutor,
        settings: Settings,
        routing_policy: ModelRoutingPolicy | None = None,
    ) -> None:
        self.executor = executor
        self.settings = settings
        self.routing_policy = routing_policy or ModelRoutingPolicy(
            terra_eligible_tiers=frozenset(settings.terra_generation_tiers)
        )
        self._model_slots = asyncio.Semaphore(settings.max_parallel_model_calls)

    async def _execute_stage(self, **kwargs: Any) -> StageExecution:
        """Apply one process-wide model-call bound across every runtime stage."""

        async with self._model_slots:
            return await self.executor.execute_stage(**kwargs)

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
        primary_timeout: float | None = None
        fallback_timeout: float | None = None
        if selected_context.public:
            retry_budget = min(
                self.settings.public_stage_timeout_seconds,
                self.settings.public_job_timeout_seconds / 2,
            )
            primary_timeout = retry_budget * (2 / 3)
            fallback_timeout = retry_budget - primary_timeout
        failure_code: str | None = None
        try:
            result = await self._execute_stage(
                prompt=prompt,
                schema_path=CODEX_OUTPUT_SCHEMA_BY_STAGE["understand"],
                model=model,
                effort="low",
                timeout_seconds=primary_timeout,
                **policy,
            )
        except CodexPolicyError:
            raise
        except CodexRuntimeError as error:
            fallback = self.settings.understand_fallback_model
            if (
                not selected_context.public
                or fallback == model
                or error.code != "schema_validation_failed"
            ):
                raise
            failure_code = error.code
        else:
            try:
                validate_understanding(result.data)
            except (ContractError, ValidationError) as error:
                fallback = self.settings.understand_fallback_model
                if not selected_context.public or fallback == model:
                    raise CodexRuntimeError(
                        "classification_validation_failed",
                        safe_detail={"kind": "contract_error", "model": model},
                    ) from error
                failure_code = "classification_validation_failed"
            else:
                return result
        LOGGER.warning(
            "public understand classification retry: primary_model=%s failure=%s "
            "fallback_model=%s",
            model,
            failure_code,
            fallback,
        )
        if selected_context.public and fallback_timeout is not None:
            retry_deadline = started + min(
                self.settings.public_stage_timeout_seconds,
                self.settings.public_job_timeout_seconds / 2,
            )
            fallback_timeout = min(fallback_timeout, retry_deadline - time.monotonic())
            if fallback_timeout <= 0:
                raise CodexRuntimeError("understand_retry_budget_exhausted")
        result = await self._execute_stage(
            prompt=prompt,
            schema_path=CODEX_OUTPUT_SCHEMA_BY_STAGE["understand"],
            model=fallback,
            effort="low",
            timeout_seconds=fallback_timeout,
            **policy,
        )
        try:
            validated_fallback = validate_understanding(result.data)
        except (ContractError, ValidationError) as error:
            raise CodexRuntimeError(
                "classification_validation_failed",
                safe_detail={"kind": "contract_error", "model": fallback},
            ) from error
        return StageExecution(
            data=validated_fallback,
            thread_id=result.thread_id,
            model=result.model,
            elapsed_ms=max(result.elapsed_ms, int((time.monotonic() - started) * 1000)),
            attempted_models=(model, fallback),
            prior_failure_codes=(failure_code or "classification_validation_failed",),
            input_tokens=result.input_tokens,
            cached_input_tokens=result.cached_input_tokens,
            output_tokens=result.output_tokens,
        )

    async def generate(
        self,
        understanding: dict[str, Any],
        scenario: str = "live",
        *,
        runtime_context: RuntimeContext | None = None,
        candidate_spec: GenerationCandidateSpec | None = None,
    ) -> StageExecution:
        del scenario
        selected_context = runtime_context or RuntimeContext()
        selected_candidate = candidate_spec or self.generation_candidate_specs(
            understanding,
            runtime_context=selected_context,
        )[0]
        return await self._execute_stage(
            prompt=self._render_prompt("generate_module.md", understanding),
            schema_path=CODEX_OUTPUT_SCHEMA_BY_STAGE["generate"],
            model=selected_candidate.model,
            effort=selected_candidate.effort,
            timeout_seconds=(
                self.settings.public_stage_timeout_seconds
                if selected_context.public
                else self.settings.evidence_stage_timeout_seconds
            ),
            **self._execution_policy(selected_context),
        )

    async def generate_fragments(
        self,
        understanding: dict[str, Any],
        *,
        runtime_context: RuntimeContext | None = None,
    ) -> tuple[StageExecution, StageExecution]:
        """Generate the scientific model and visual plan concurrently.

        Both calls are required.  If either fails or the learner cancels, the
        sibling is cancelled and awaited so its subprocess group cannot outlive
        the public job.
        """

        selected_context = runtime_context or RuntimeContext()
        policy = self._execution_policy(selected_context)
        timeout_seconds = (
            self.settings.public_stage_timeout_seconds
            if selected_context.public
            else self.settings.evidence_stage_timeout_seconds
        )
        physics_task = asyncio.create_task(
            self._execute_stage(
                prompt=self._render_prompt("generate_physics.md", understanding),
                schema_path=CODEX_OUTPUT_SCHEMA_BY_STAGE["generate_physics"],
                model=self.settings.physics_model,
                effort="medium",
                timeout_seconds=timeout_seconds,
                **policy,
            )
        )
        visual_task = asyncio.create_task(
            self._execute_stage(
                prompt=self._render_prompt("generate_visual.md", understanding),
                schema_path=CODEX_OUTPUT_SCHEMA_BY_STAGE["generate_visual"],
                model=self.settings.visual_model,
                effort="medium",
                timeout_seconds=timeout_seconds,
                **policy,
            )
        )
        tasks = (physics_task, visual_task)
        try:
            physics, visual = await asyncio.gather(*tasks)
            return physics, visual
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def regenerate_fragment(
        self,
        role: Literal["physics", "visual"],
        understanding: dict[str, Any],
        failure_code: str,
        *,
        exact_gate_failures: list[dict[str, Any]] | None = None,
        prior_fragment: dict[str, Any] | None = None,
        repair_attempt: int = 1,
        runtime_context: RuntimeContext | None = None,
    ) -> StageExecution:
        """Regenerate one invalid fragment within the two-attempt public bound."""

        if role not in {"physics", "visual"}:
            raise ValueError("unknown fragment role")
        if repair_attempt not in {1, 2}:
            raise ValueError("fragment repair attempt must be one or two")
        safe_failure_code = (
            failure_code
            if failure_code.replace("_", "").isalnum() and len(failure_code) <= 64
            else "fragment_semantic_validation_failed"
        )
        retry_hint = FRAGMENT_RETRY_HINTS.get(safe_failure_code, "")
        if safe_failure_code == "physics_fixture_mismatch":
            retry_hint = (
                "Re-derive every expression from the fixed numeric and relation checks in "
                "UNDERSTANDING_JSON. Match expected values within tolerance and keep fixed "
                "constants as numeric literals."
            )
        elif safe_failure_code == "visual_geometry_mismatch":
            retry_hint = (
                "Keep every scientific actor and its conservative safety envelope inside "
                "the viewport at narrow and wide sizes. Avoid forbidden overlap and retain "
                "a clear mobile margin."
            )
        elif safe_failure_code == "visual_causality_mismatch":
            retry_hint = (
                "Bind the primary scientific actor response channel directly to its "
                "fixture-covered causal output. Preserve the declared relation across "
                "boundary states and keep the full displacement visibly salient. "
                "Re-select actor_archetype only after the commands are final, then verify "
                "that its scientific command kinds and counts match and that every proof "
                "channel remains backed by the emitted actor."
            )
        elif safe_failure_code == "visual_quality_review_failed":
            retry_hint = (
                "Improve scene depth, physical lighting, idle motion, reactive feedback, "
                "and readable overlays while preserving the fixed physics, causal binding, "
                "and controls. Keep scientific actors clear at mobile viewport sizes."
            )
        selected_context = runtime_context or RuntimeContext()
        prompt_name = f"generate_{role}.md"
        stage_name = f"generate_{role}"
        primary_model = (
            self.settings.physics_model if role == "physics" else self.settings.visual_model
        )
        model = self.settings.heal_model if repair_attempt == 2 else primary_model
        prompt = self._render_prompt(prompt_name, understanding) + (
            "\n\nDETERMINISTIC_RETRY:\n"
            "Return a corrected fragment for the same fixed understanding. "
            f"This is bounded repair attempt {repair_attempt} of 2. "
            "The prior response was rejected by the trusted semantic validator. "
            f"Failure code: {safe_failure_code}. "
            "Return the complete corrected fragment. Preserve every valid field from "
            "CURRENT_FRAGMENT_JSON unless an exact failure requires changing it, and "
            "independently satisfy every base fragment rule. Do not discuss the repair. "
            f"ACTIONABLE_RULE: {retry_hint}"
            "\nCURRENT_FRAGMENT_JSON:\n"
            + json.dumps(
                prior_fragment or {},
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\nEXACT_GATE_FAILURES_JSON:\n"
            + json.dumps(
                exact_gate_failures or [],
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        timeout_seconds = (
            self.settings.public_stage_timeout_seconds
            if selected_context.public
            else self.settings.evidence_stage_timeout_seconds
        )
        return await self._execute_stage(
            prompt=prompt,
            schema_path=CODEX_OUTPUT_SCHEMA_BY_STAGE[stage_name],
            model=model,
            effort="medium",
            timeout_seconds=timeout_seconds,
            **self._execution_policy(selected_context),
        )

    def generation_candidate_specs(
        self,
        understanding: dict[str, Any],
        *,
        runtime_context: RuntimeContext | None = None,
    ) -> tuple[GenerationCandidateSpec, ...]:
        """Return the bounded internal race without exposing routing to learners."""

        selected_context = runtime_context or RuntimeContext()
        if not selected_context.public:
            return (
                GenerationCandidateSpec(
                    "single", 1, self.settings.generate_model, "medium"
                ),
            )
        if self.settings.public_generate_model_override is not None:
            return (
                GenerationCandidateSpec(
                    "single",
                    1,
                    self.settings.public_generate_model_override,
                    self.settings.public_generate_effort,
                ),
            )
        routing_policy = getattr(
            self,
            "routing_policy",
            ModelRoutingPolicy(
                terra_eligible_tiers=frozenset(self.settings.terra_generation_tiers)
            ),
        )
        routed_model = routing_policy.generation_model(understanding)
        if self.settings.public_candidate_count == 2:
            return (
                GenerationCandidateSpec("fast", 1, "gpt-5.6-terra", "medium"),
                GenerationCandidateSpec("quality", 2, "gpt-5.6-sol", "medium"),
            )
        return (
            GenerationCandidateSpec(
                "quality" if routed_model == "gpt-5.6-sol" else "single",
                1,
                routed_model,
                self.settings.public_generate_effort,
            ),
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
        selected_context = runtime_context or RuntimeContext()
        model = (
            self.routing_policy.heal_model(understanding, attempt)
            if selected_context.public
            else self.settings.heal_model
        )
        return await self._execute_stage(
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
            model=model,
            effort="high" if attempt == 2 else "medium",
            **self._execution_policy(selected_context),
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
        return await self._execute_stage(
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

    async def visual_qa(
        self,
        understanding: dict[str, Any],
        screenshots: tuple[Path, Path, Path],
        gate_outcome: dict[str, Any],
        *,
        runtime_context: RuntimeContext | None = None,
    ) -> StageExecution:
        selected_context = runtime_context or RuntimeContext()
        if selected_context.public or selected_context.evidence_fixture_id is None:
            raise CodexPolicyError("visual_qa_curated_only")
        if gate_outcome.get("passed") is not True:
            raise CodexPolicyError("visual_qa_requires_passing_gates")
        payload = {
            "module_spec": understanding["module_spec"],
            "primary_parameter": understanding["primary_parameter"],
            "key_formula": understanding["key_formula"],
            "gate_outcome": gate_outcome,
            "screenshot_order": ["initial", "mid_action", "parameter_changed"],
        }
        return await self._execute_stage(
            prompt=self._render_prompt("visual_qa.md", payload),
            schema_path=CODEX_OUTPUT_SCHEMA_BY_STAGE["visual_qa"],
            model=self.settings.visual_qa_model,
            effort="low",
            image_paths=screenshots,
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
    suggestions = (
        [
            "لماذا يتغير شكل القمر؟",
            "كيف يؤثر طول البندول في زمنه؟",
            "لماذا تطفو بعض الأجسام؟",
        ]
        if arabic
        else [
            "Why does the Moon change shape?",
            "How does pendulum length affect its period?",
            "Why do some objects float?",
        ]
    )
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
            "suggestions": suggestions,
        }
    )


def _unsafe(locale: str) -> dict[str, Any]:
    arabic = locale != "en"
    suggestions = (
        [
            "لماذا يتغير شكل القمر؟",
            "كيف تعمل الدائرة الكهربائية البسيطة؟",
            "لماذا يتغير ارتفاع الصوت؟",
        ]
        if arabic
        else [
            "Why does the Moon change shape?",
            "How does a simple circuit work?",
            "Why does sound pitch change?",
        ]
    )
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
            "suggestions": suggestions,
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
