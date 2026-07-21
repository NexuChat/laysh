from __future__ import annotations

from pathlib import Path

from scripts.check_no_example_specific_runtime import audit_repository


def _write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _codes(root: Path) -> set[str]:
    return {finding.code for finding in audit_repository(root)}


def test_current_production_runtime_has_no_example_specific_correctness_logic() -> None:
    root = Path(__file__).parents[1]

    assert audit_repository(root) == []


def test_rejects_example_specific_import_from_production_runtime(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "server/verify.py",
        "from server.golden_geometry import upgrade_moon_geometry\n",
    )
    _write(tmp_path, "server/golden_geometry.py", "def upgrade_moon_geometry(): ...\n")

    assert "example_specific_import" in _codes(tmp_path)


def test_rejects_lesson_or_question_keyed_execution_branches(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "server/pipeline.py",
        """
def select_layout(lesson_id, question):
    if lesson_id == "moon":
        return "compact"
    if "pendulum" in question.lower():
        return "wide"
    return "stacked"
""",
    )

    findings = audit_repository(tmp_path)

    assert [finding.code for finding in findings].count("example_specific_branch") == 2


def test_rejects_custom_identifiers_and_slug_keyed_coordinates(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "server/assemble.py",
        """
def patch_buoyancy_layout(scene):
    moon_x = 27
    return scene

LESSON_LAYOUTS = {"day_night": {"x": 18, "y": 42}}
""",
    )

    codes = _codes(tmp_path)

    assert "example_specific_identifier" in codes
    assert "example_specific_coordinates" in codes


def test_rejects_per_lesson_prompt_filename(tmp_path: Path) -> None:
    _write(tmp_path, "server/pipeline.py", "def run(): ...\n")
    _write(tmp_path, "server/prompts/simple_circuit.md", "Generate a circuit.\n")

    assert "example_specific_prompt" in _codes(tmp_path)


def test_allows_reference_tooling_and_generic_golden_infrastructure(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "server/cache.py",
        """
from server.goldens import load_pinned_golden

def find(golden_root, golden_id, cache_id):
    if cache_id.startswith("golden_"):
        return golden_root / golden_id
    return None
""",
    )
    _write(
        tmp_path,
        "server/golden_geometry.py",
        """
def patch_moon_layout(golden_id):
    if golden_id == "moon_phases":
        return {"x": 27, "y": 42}
    return None
""",
    )
    _write(
        tmp_path,
        "server/physics_motion.py",
        """
def pendulum_known_case():
    return {"period_seconds": 2.0}
""",
    )
    _write(
        tmp_path,
        "scripts/refresh_pinned_moon_geometry.py",
        "from server.golden_geometry import patch_moon_layout\n",
    )
    _write(
        tmp_path,
        "tests/fixtures/moon_case.py",
        "MOON_X = 27\n",
    )

    assert audit_repository(tmp_path) == []


def test_allows_general_model_families_and_scientific_primitives(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "server/pipeline.py",
        """
MODEL_FAMILIES = {"moon_phase_geometry": "orbit"}

def resolve_model_family(intent):
    if intent.model_family == "moon_phase_geometry":
        return MODEL_FAMILIES[intent.model_family]
    return "generic"
""",
    )

    assert audit_repository(tmp_path) == []


def test_rejects_orphaned_generated_shared_validator(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "server/scene_geometry.py",
        "def validate_scene_geometry(samples): return samples\n",
    )
    _write(
        tmp_path,
        "server/verify.py",
        "from server.scene_geometry import validate_scene_geometry\n",
    )
    _write(
        tmp_path,
        "server/golden_physics_motion.py",
        """
from server.scene_geometry import validate_scene_geometry

def evaluate(samples):
    return validate_scene_geometry(samples)
""",
    )

    assert "generated_shared_validator_call_missing" in _codes(tmp_path)


def test_rejects_curated_validator_that_does_not_delegate_to_shared_symbol(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "server/scene_geometry.py",
        "def validate_scene_geometry(samples): return samples\n",
    )
    _write(
        tmp_path,
        "server/verify.py",
        """
from server.scene_geometry import validate_scene_geometry

def verify(samples):
    return validate_scene_geometry(samples)
""",
    )
    _write(
        tmp_path,
        "server/golden_physics_motion.py",
        """
from server.golden_geometry import evaluate_body_geometry

def evaluate(samples):
    return evaluate_body_geometry(samples)
""",
    )

    codes = _codes(tmp_path)

    assert "curated_shared_validator_import_missing" in codes
    assert "curated_shared_validator_call_missing" in codes
    assert "curated_imports_example_validator" in codes


def test_accepts_both_paths_calling_the_same_shared_validator(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "server/scene_geometry.py",
        "def validate_scene_geometry(samples): return samples\n",
    )
    _write(
        tmp_path,
        "server/verify.py",
        """
from server.scene_geometry import validate_scene_geometry

def verify(samples):
    return validate_scene_geometry(samples)
""",
    )
    _write(
        tmp_path,
        "server/golden_physics_motion.py",
        """
from server.scene_geometry import validate_scene_geometry

def evaluate(samples):
    return validate_scene_geometry(samples)
""",
    )

    assert audit_repository(tmp_path) == []
