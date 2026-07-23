from __future__ import annotations

import asyncio
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import ValidationError

from tests.golden_cases import VALID_UNDERSTANDING

PHYSICS_FRAGMENT = {
    "physics_expressions": [
        {
            "name": "lit_fraction",
            "expression": "(1 - cos(angle_deg * pi / 180)) / 2",
        }
    ],
    "output_names": ["lit_fraction"],
    "brief_summary": "يربط زاوية المدار بالجزء المضيء المرئي.",
    "assumptions": ["مدار دائري مبسط"],
}

SCIENTIFIC_CIRCLE = {
    "kind": "circle",
    "id": "actor",
    "scientific": True,
    "clipping_policy": "forbid",
    "cx": "width / 2",
    "cy": "height / 2",
    "radius": "min(30, min_dim * 0.12)",
    "fill_color": "#F7E7A9",
    "fill_alt_color": "#D08A32",
    "stroke_color": "#FFFFFF",
    "line_width": "2",
    "opacity": "0.55 + output_lit_fraction * 0.45",
}

VISUAL_FRAGMENT = {
    "background": {
        "top_color": "#07111F",
        "bottom_color": "#10243A",
    },
    "commands": [SCIENTIFIC_CIRCLE],
    "relations": [],
    "causal_response": {
        "actor_id": "actor",
        "output_name": "lit_fraction",
        "channel": "opacity",
        "relation": "direct",
        "temporal_mode": "parameter_driven",
    },
}

TEXT_COMMAND = {
    "kind": "text",
    "id": "caption",
    "scientific": False,
    "clipping_policy": "forbid",
    "x": "width / 2",
    "y": "32",
    "text_ar": "الجزء المضيء",
    "text_en": "Lit fraction",
    "color": "#FFFFFF",
    "font_size": "16",
    "align": "center",
    "opacity": "1",
}

SCIENTIFIC_ELLIPSE = {
    "kind": "ellipse",
    "id": "elongated_actor",
    "scientific": True,
    "clipping_policy": "forbid",
    "cx": "width / 2",
    "cy": "height / 2 + sin(phase * 0.2) * 2",
    "radius_x": "min_dim * (0.18 + output_lit_fraction * 0.03)",
    "radius_y": "min_dim * 0.07",
    "rotation": "normalized * 0.2",
    "fill_color": "#58B7FF",
    "fill_alt_color": "#B8E3FF",
    "stroke_color": "#FFFFFF",
    "line_width": "2",
    "opacity": "1",
}

UNSAFE_EXPRESSIONS = [
    pytest.param("angle_deg.real", id="attribute"),
    pytest.param("angle_deg[0]", id="subscript"),
    pytest.param("(lambda value: value)(angle_deg)", id="lambda"),
    pytest.param("sum(value for value in [angle_deg])", id="comprehension"),
    pytest.param("__import__('os').system('id')", id="import-call"),
    pytest.param("import os", id="import-statement"),
    pytest.param(r"\u0066etch(angle_deg)", id="unicode-escape"),
    pytest.param("0; window.LayshSimulation = {}", id="statement-closeout"),
]


def test_physics_fragment_schema_is_closed_and_matches_the_understanding_outputs():
    from server.fragment_generation import validate_physics_fragment

    document = deepcopy(PHYSICS_FRAGMENT)

    assert validate_physics_fragment(document, VALID_UNDERSTANDING) == document

    with pytest.raises(ValidationError):
        validate_physics_fragment({**document, "reasoning": "private"}, VALID_UNDERSTANDING)
    with pytest.raises(ValidationError):
        validate_physics_fragment(
            {
                **document,
                "physics_expressions": [
                    {**document["physics_expressions"][0], "source_js": "fetch('/')"}
                ],
            },
            VALID_UNDERSTANDING,
        )


@pytest.mark.parametrize("missing", PHYSICS_FRAGMENT)
def test_physics_fragment_schema_requires_every_public_field(missing):
    from server.fragment_generation import validate_physics_fragment

    document = deepcopy(PHYSICS_FRAGMENT)
    document.pop(missing)

    with pytest.raises(ValidationError):
        validate_physics_fragment(document, VALID_UNDERSTANDING)


def test_physics_fragment_rejects_raw_javascript_body_and_output_drift():
    from server.fragment_generation import validate_physics_fragment
    from server.schemas import ContractError

    with pytest.raises(ValidationError):
        validate_physics_fragment(
            {**PHYSICS_FRAGMENT, "physics_body": "return { lit_fraction: 0 };"},
            VALID_UNDERSTANDING,
        )

    document = {**PHYSICS_FRAGMENT, "output_names": ["invented_output"]}
    with pytest.raises(ContractError, match="output"):
        validate_physics_fragment(document, VALID_UNDERSTANDING)


def test_physics_fragment_requires_one_expression_for_each_declared_output():
    from server.fragment_generation import validate_physics_fragment
    from server.schemas import ContractError

    missing = {**PHYSICS_FRAGMENT, "physics_expressions": []}
    duplicate = {
        **PHYSICS_FRAGMENT,
        "physics_expressions": [
            *PHYSICS_FRAGMENT["physics_expressions"],
            *PHYSICS_FRAGMENT["physics_expressions"],
        ],
    }

    with pytest.raises((ValidationError, ContractError)):
        validate_physics_fragment(missing, VALID_UNDERSTANDING)
    with pytest.raises(ContractError, match="output|expression"):
        validate_physics_fragment(duplicate, VALID_UNDERSTANDING)


@pytest.mark.parametrize("expression", UNSAFE_EXPRESSIONS)
def test_physics_expression_ast_rejects_code_capabilities(expression):
    from server.fragment_generation import validate_physics_fragment

    document = deepcopy(PHYSICS_FRAGMENT)
    document["physics_expressions"][0]["expression"] = expression

    with pytest.raises(ValueError):
        validate_physics_fragment(document, VALID_UNDERSTANDING)


def test_visual_fragment_schema_is_closed_at_root_background_and_command_levels():
    from server.fragment_generation import validate_visual_fragment

    document = deepcopy(VISUAL_FRAGMENT)
    assert validate_visual_fragment(document, VALID_UNDERSTANDING) == document

    with pytest.raises(ValidationError):
        validate_visual_fragment({**document, "visual_body": "fetch('/')"}, VALID_UNDERSTANDING)
    with pytest.raises(ValidationError):
        validate_visual_fragment(
            {
                **document,
                "background": {**document["background"], "image_url": "https://invalid"},
            },
            VALID_UNDERSTANDING,
        )
    with pytest.raises(ValidationError):
        validate_visual_fragment(
            {
                **document,
                "commands": [{**document["commands"][0], "javascript": "postMessage(1)"}],
            },
            VALID_UNDERSTANDING,
        )


@pytest.mark.parametrize("missing", VISUAL_FRAGMENT)
def test_visual_fragment_schema_requires_background_commands_and_relations(missing):
    from server.fragment_generation import validate_visual_fragment

    document = deepcopy(VISUAL_FRAGMENT)
    document.pop(missing)

    with pytest.raises(ValidationError):
        validate_visual_fragment(document, VALID_UNDERSTANDING)


def test_visual_command_branch_is_closed_fully_required_and_non_nullable():
    from server.fragment_generation import validate_visual_fragment

    missing_radius = deepcopy(VISUAL_FRAGMENT)
    missing_radius["commands"][0].pop("radius")
    wrong_branch_field = deepcopy(VISUAL_FRAGMENT)
    wrong_branch_field["commands"][0]["x"] = "0"
    nullable_radius = deepcopy(VISUAL_FRAGMENT)
    nullable_radius["commands"][0]["radius"] = None

    for document in (missing_radius, wrong_branch_field, nullable_radius):
        with pytest.raises(ValidationError):
            validate_visual_fragment(document, VALID_UNDERSTANDING)


@pytest.mark.parametrize("expression", UNSAFE_EXPRESSIONS)
def test_visual_numeric_expression_uses_the_same_ast_allowlist(expression):
    from server.fragment_generation import validate_visual_fragment

    document = deepcopy(VISUAL_FRAGMENT)
    document["commands"][0]["opacity"] = expression

    with pytest.raises(ValueError):
        validate_visual_fragment(document, VALID_UNDERSTANDING)


def test_visual_scientific_geometry_must_consume_declared_outputs_not_raw_inputs():
    from server.fragment_generation import validate_visual_fragment
    from server.schemas import ContractError

    no_output = deepcopy(VISUAL_FRAGMENT)
    no_output["commands"][0]["opacity"] = "0.75"
    duplicate_formula = deepcopy(VISUAL_FRAGMENT)
    duplicate_formula["commands"][0]["opacity"] = (
        "(1 - cos(angle_deg * pi / 180)) / 2"
    )
    unknown_output = deepcopy(VISUAL_FRAGMENT)
    unknown_output["commands"][0]["opacity"] = "output_invented"

    with pytest.raises(ContractError, match="output"):
        validate_visual_fragment(no_output, VALID_UNDERSTANDING)
    with pytest.raises(ValueError):
        validate_visual_fragment(duplicate_formula, VALID_UNDERSTANDING)
    with pytest.raises(ContractError, match="output"):
        validate_visual_fragment(unknown_output, VALID_UNDERSTANDING)


def test_trusted_visual_grammar_compiles_ellipse_with_a_conservative_safety_envelope():
    from server.fragment_generation import assemble_fragments, validate_visual_fragment
    from server.verify import verify_candidate

    document = {
        **deepcopy(VISUAL_FRAGMENT),
        "commands": [deepcopy(SCIENTIFIC_ELLIPSE)],
        "causal_response": {
            **VISUAL_FRAGMENT["causal_response"],
            "actor_id": "elongated_actor",
            "channel": "size",
        },
    }

    assert validate_visual_fragment(document, VALID_UNDERSTANDING) == document
    module_output = assemble_fragments(
        deepcopy(PHYSICS_FRAGMENT),
        document,
        deepcopy(VALID_UNDERSTANDING),
    )
    source = module_output["module_js"]
    assert "context.ellipse(" in source
    assert 'geometry:{type:"circle",cx,cy,radius:Math.max(radiusX,radiusY)}' in source
    assert verify_candidate(module_output, deepcopy(VALID_UNDERSTANDING)).passed is True


def test_scientific_ellipse_cannot_hide_output_response_in_line_width_only():
    from server.fragment_generation import validate_visual_fragment
    from server.schemas import ContractError

    command = {
        **deepcopy(SCIENTIFIC_ELLIPSE),
        "radius_x": "min_dim * 0.18",
        "line_width": "1 + output_lit_fraction",
    }
    document = {
        **deepcopy(VISUAL_FRAGMENT),
        "commands": [command],
        "causal_response": {
            **VISUAL_FRAGMENT["causal_response"],
            "actor_id": "elongated_actor",
            "channel": "size",
        },
    }

    with pytest.raises(ContractError, match="salient"):
        validate_visual_fragment(document, VALID_UNDERSTANDING)


def test_ellipse_safety_envelope_cannot_claim_required_shape_contact():
    from server.fragment_generation import validate_visual_fragment
    from server.schemas import ContractError

    second = {**SCIENTIFIC_CIRCLE, "id": "round_actor", "cx": "width * 0.75"}
    document = {
        **deepcopy(VISUAL_FRAGMENT),
        "commands": [deepcopy(SCIENTIFIC_ELLIPSE), second],
        "relations": [
            {
                "objects": ["elongated_actor", "round_actor"],
                "overlap_policy": "allow",
                "contact_policy": "required",
                "minimum_clearance": "0",
            }
        ],
    }

    with pytest.raises(ContractError, match="ellipse|required contact"):
        validate_visual_fragment(document, VALID_UNDERSTANDING)


def test_forbidden_ellipse_geometry_is_fitted_before_shared_evidence():
    from server.fragment_generation import assemble_fragments
    from server.verify import verify_candidate

    oversized = {
        **deepcopy(SCIENTIFIC_ELLIPSE),
        "cx": "-200",
        "cy": "height * 4",
        "radius_x": "width * 2",
        "radius_y": "height * 2",
        "opacity": "0.55 + output_lit_fraction * 0.45",
    }
    document = {
        **deepcopy(VISUAL_FRAGMENT),
        "commands": [oversized],
        "causal_response": {
            **VISUAL_FRAGMENT["causal_response"],
            "actor_id": "elongated_actor",
            "channel": "opacity",
        },
    }
    module_output = assemble_fragments(
        deepcopy(PHYSICS_FRAGMENT),
        document,
        deepcopy(VALID_UNDERSTANDING),
    )

    result = verify_candidate(module_output, deepcopy(VALID_UNDERSTANDING))

    assert result.passed is True, result.failures
    assert "const fitScale" in module_output["module_js"]


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "</script><script>postMessage(1)</script>",
        "@@MODULE_JS@@",
        "/* LAYSH_SHARED_MODEL: modelState */",
        "safe\u202etxt",
    ],
)
def test_visual_text_rejects_script_shell_markers_and_bidi_controls(unsafe_text):
    from server.fragment_generation import validate_visual_fragment

    document = deepcopy(VISUAL_FRAGMENT)
    command = {**TEXT_COMMAND, "text_ar": unsafe_text}
    document["commands"].append(command)

    with pytest.raises(ValueError):
        validate_visual_fragment(document, VALID_UNDERSTANDING)


def test_relations_are_closed_reference_existing_objects_and_cover_scientific_pairs():
    from server.fragment_generation import validate_visual_fragment
    from server.schemas import ContractError

    second = {**SCIENTIFIC_CIRCLE, "id": "actor_two", "cx": "width * 0.75"}
    missing_relation = {
        **deepcopy(VISUAL_FRAGMENT),
        "commands": [deepcopy(SCIENTIFIC_CIRCLE), second],
    }
    valid_relation = {
        **missing_relation,
        "relations": [
            {
                "objects": ["actor", "actor_two"],
                "overlap_policy": "forbid",
                "contact_policy": "forbid",
                "minimum_clearance": "8",
            }
        ],
    }
    unknown_object = deepcopy(valid_relation)
    unknown_object["relations"][0]["objects"][1] = "missing"
    extra_field = deepcopy(valid_relation)
    extra_field["relations"][0]["script"] = "fetch('/')"

    with pytest.raises(ContractError, match="relation|scientific"):
        validate_visual_fragment(missing_relation, VALID_UNDERSTANDING)
    assert validate_visual_fragment(valid_relation, VALID_UNDERSTANDING) == valid_relation
    with pytest.raises(ContractError, match="relation|object"):
        validate_visual_fragment(unknown_object, VALID_UNDERSTANDING)
    with pytest.raises(ValidationError):
        validate_visual_fragment(extra_field, VALID_UNDERSTANDING)


def test_fragment_assembler_is_deterministic_and_owns_the_six_key_abi():
    from server.fragment_generation import assemble_fragments
    from server.verify import PERMITTED_ABI, verify_module_with_node

    first = assemble_fragments(
        deepcopy(PHYSICS_FRAGMENT),
        deepcopy(VISUAL_FRAGMENT),
        deepcopy(VALID_UNDERSTANDING),
    )
    second = assemble_fragments(
        deepcopy(PHYSICS_FRAGMENT),
        deepcopy(VISUAL_FRAGMENT),
        deepcopy(VALID_UNDERSTANDING),
    )

    assert first == second
    assert set(first) == {"module_js", "output_names", "brief_summary", "assumptions"}
    assert first["output_names"] == PHYSICS_FRAGMENT["output_names"]
    assert first["brief_summary"] == PHYSICS_FRAGMENT["brief_summary"]
    assert first["assumptions"] == PHYSICS_FRAGMENT["assumptions"]
    assert first["module_js"].count("window.LayshSimulation") == 1
    assert len(PERMITTED_ABI) == 6
    node_report = verify_module_with_node(first["module_js"], VALID_UNDERSTANDING)
    assert node_report["passed"] is True


def test_assembled_draw_and_test_share_model_state_as_the_only_physics_source():
    from server.fragment_generation import assemble_fragments
    from server.shared_state import shared_model_report

    module_output = assemble_fragments(
        PHYSICS_FRAGMENT,
        VISUAL_FRAGMENT,
        VALID_UNDERSTANDING,
    )

    report = shared_model_report(module_output["module_js"])
    assert report["passed"] is True
    assert report["model_function"] == "modelState"
    assert module_output["module_js"].count("/* LAYSH_SHARED_MODEL: modelState */") == 1
    assert module_output["module_js"].count("function modelState(") == 1


def test_declarative_visual_cannot_override_physics_test_or_the_public_interface():
    from server.fragment_generation import assemble_fragments, validate_visual_fragment

    document = {
        **VISUAL_FRAGMENT,
        "test": {"lit_fraction": 0},
        "window.LayshSimulation": {"version": 99},
    }

    with pytest.raises(ValidationError):
        validate_visual_fragment(document, VALID_UNDERSTANDING)
    with pytest.raises(ValidationError):
        assemble_fragments(PHYSICS_FRAGMENT, document, VALID_UNDERSTANDING)


def test_small_valid_declarative_pair_passes_the_existing_candidate_verifier():
    from server.fragment_generation import assemble_fragments
    from server.verify import verify_candidate

    module_output = assemble_fragments(
        deepcopy(PHYSICS_FRAGMENT),
        deepcopy(VISUAL_FRAGMENT),
        deepcopy(VALID_UNDERSTANDING),
    )

    result = verify_candidate(module_output, deepcopy(VALID_UNDERSTANDING))

    assert result.passed is True, result.failures
    assert result.artifact is not None
    assert result.node_report["passed"] is True
    assert result.node_report["fixture_count"] == len(VALID_UNDERSTANDING["checks"])


class _BlockingFragmentExecutor:
    def __init__(self) -> None:
        self.entered = {
            "physics_fragment.schema.json": asyncio.Event(),
            "visual_fragment.schema.json": asyncio.Event(),
        }
        self.release = {
            "physics_fragment.schema.json": asyncio.Event(),
            "visual_fragment.schema.json": asyncio.Event(),
        }
        self.active = 0
        self.peak = 0
        self.calls: list[tuple[str, str]] = []

    async def execute_stage(self, **kwargs):
        from server.codex_runtime import StageExecution

        schema_name = Path(kwargs["schema_path"]).name
        self.calls.append((schema_name, kwargs["model"]))
        self.active += 1
        self.peak = max(self.peak, self.active)
        self.entered[schema_name].set()
        try:
            await self.release[schema_name].wait()
            data = PHYSICS_FRAGMENT if schema_name.startswith("physics") else VISUAL_FRAGMENT
            return StageExecution(
                data=deepcopy(data),
                thread_id=f"offline-{schema_name}",
                model=kwargs["model"],
                elapsed_ms=1,
            )
        finally:
            self.active -= 1


@pytest.mark.asyncio
async def test_backend_starts_both_fragment_model_calls_concurrently_and_returns_role_order():
    from server.codex_backend import CodexBackend
    from server.settings import Settings

    executor = _BlockingFragmentExecutor()
    backend = CodexBackend(
        executor=executor,
        settings=Settings(max_parallel_model_calls=2),
    )
    generation = asyncio.create_task(backend.generate_fragments(VALID_UNDERSTANDING))

    await asyncio.wait_for(
        asyncio.gather(*(event.wait() for event in executor.entered.values())),
        timeout=1,
    )
    assert executor.active == executor.peak == 2

    executor.release["visual_fragment.schema.json"].set()
    await asyncio.sleep(0)
    assert generation.done() is False

    executor.release["physics_fragment.schema.json"].set()
    physics_stage, visual_stage = await asyncio.wait_for(generation, timeout=1)

    assert physics_stage.data == PHYSICS_FRAGMENT
    assert visual_stage.data == VISUAL_FRAGMENT
    assert executor.peak == 2
    assert sorted(executor.calls) == [
        ("physics_fragment.schema.json", "gpt-5.6-sol"),
        ("visual_fragment.schema.json", "gpt-5.6-terra"),
    ]


class _FragmentPipelineBackend:
    backend_name = "mock"

    def __init__(self) -> None:
        from server.codex_backend import MockCodexBackend

        self._delegate = MockCodexBackend()
        self.release_physics = asyncio.Event()
        self.release_visual = asyncio.Event()
        self.physics_entered = asyncio.Event()
        self.visual_entered = asyncio.Event()
        self.physics_completed = asyncio.Event()
        self.visual_completed = asyncio.Event()
        self.qa_calls = 0

    def scenario_for(self, question: str) -> str:
        return self._delegate.scenario_for(question)

    async def understand(self, *args, **kwargs):
        return await self._delegate.understand(*args, **kwargs)

    async def generate(self, *args, **kwargs):
        raise AssertionError("the fragmented route must not call monolithic generation")

    async def generate_fragments(self, *args, **kwargs):
        from server.codex_runtime import StageExecution

        del args, kwargs

        async def physics_call():
            self.physics_entered.set()
            await self.release_physics.wait()
            self.physics_completed.set()
            return StageExecution(
                data=deepcopy(PHYSICS_FRAGMENT),
                thread_id="offline-physics",
                model="gpt-5.6-sol",
                elapsed_ms=1,
            )

        async def visual_call():
            self.visual_entered.set()
            await self.release_visual.wait()
            self.visual_completed.set()
            return StageExecution(
                data=deepcopy(VISUAL_FRAGMENT),
                thread_id="offline-visual",
                model="gpt-5.6-terra",
                elapsed_ms=1,
            )

        physics_stage, visual_stage = await asyncio.gather(physics_call(), visual_call())
        return physics_stage, visual_stage

    async def heal(self, *args, **kwargs):
        return await self._delegate.heal(*args, **kwargs)

    async def qa(self, *args, **kwargs):
        self.qa_calls += 1
        return await self._delegate.qa(*args, **kwargs)


class _PublishOrderCache:
    def __init__(
        self,
        backend: _FragmentPipelineBackend,
        verification_completed: threading.Event,
    ) -> None:
        self.backend = backend
        self.verification_completed = verification_completed
        self.writes: list[dict[str, Any]] = []

    def lookup(self, **kwargs):
        del kwargs
        return None

    def write_verified(self, **kwargs):
        assert self.backend.physics_completed.is_set()
        assert self.backend.visual_completed.is_set()
        assert self.verification_completed.is_set()
        self.writes.append(kwargs)


@pytest.mark.asyncio
async def test_pipeline_does_not_publish_or_cache_until_both_fragments_and_verification_finish(
    monkeypatch,
):
    from server.browser_verify import BrowserVerificationResult
    from server.jobs import JobManager
    from server.verify import VerificationResult

    backend = _FragmentPipelineBackend()
    verification_entered = threading.Event()
    verification_release = threading.Event()
    verification_completed = threading.Event()

    def blocking_verification(module_output, understanding):
        assert module_output["module_js"]
        assert understanding["module_spec"]["outputs"] == ["lit_fraction"]
        assert backend.physics_completed.is_set()
        assert backend.visual_completed.is_set()
        verification_entered.set()
        assert verification_release.wait(timeout=1)
        verification_completed.set()
        return VerificationResult(
            passed=True,
            check_count=17,
            failures=[],
            artifact="<!doctype html><html><body>verified fragments</body></html>",
            node_report={"passed": True},
        )

    monkeypatch.setattr("server.pipeline.verify_candidate", blocking_verification)
    cache = _PublishOrderCache(backend, verification_completed)
    manager = JobManager(
        backend,
        public_job_timeout_seconds=2,
        browser_verifier=lambda _: BrowserVerificationResult.passing(),
        cache=cache,
    )
    record = manager.start("success", "ar")

    await asyncio.wait_for(
        asyncio.gather(
            backend.physics_entered.wait(),
            backend.visual_entered.wait(),
        ),
        timeout=1,
    )
    assert record.artifact is None
    assert manager.artifacts == {}
    assert cache.writes == []

    backend.release_physics.set()
    await asyncio.wait_for(backend.physics_completed.wait(), timeout=1)
    assert backend.visual_completed.is_set() is False
    assert record.artifact is None
    assert manager.artifacts == {}
    assert cache.writes == []

    backend.release_visual.set()
    assert await asyncio.to_thread(verification_entered.wait, 1)
    assert verification_completed.is_set() is False
    assert record.artifact is None
    assert manager.artifacts == {}
    assert cache.writes == []

    verification_release.set()
    await asyncio.wait_for(record.task, timeout=1)

    assert record.status == "complete"
    assert record.artifact is not None
    assert len(manager.artifacts) == 1
    assert len(cache.writes) == 1
    assert [
        (receipt.stage, receipt.attempt, receipt.model, receipt.outcome)
        for receipt in record.runtime_receipts
        if receipt.stage == "generate"
    ] == [
        ("generate", 1, "gpt-5.6-sol", "completed"),
        ("generate", 2, "gpt-5.6-terra", "completed"),
    ]
    assert [
        execution.get("fragment_role")
        for execution in record.stage_executions
        if execution["stage"] == "generate"
    ] == ["physics", "visual"]
    assert record.simulation is not None
    assert record.simulation.effective_model == (
        "physics:gpt-5.6-sol+visual:gpt-5.6-terra"
    )
