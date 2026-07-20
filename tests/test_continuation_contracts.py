from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def _source_with_exact_utf8_size(size: int, character: str) -> str:
    encoded_character = character.encode("utf-8")
    count, remainder = divmod(size, len(encoded_character))
    return character * count + ("x" * remainder)


@pytest.mark.parametrize("character", ["x", "−"])
@pytest.mark.parametrize("delta, exceeds", [(-1, False), (0, False), (1, True)])
def test_generated_source_limit_is_96_kib_of_utf8_bytes(character, delta, exceeds):
    from server.verify import MAX_SOURCE_BYTES, _source_report

    source = _source_with_exact_utf8_size(MAX_SOURCE_BYTES + delta, character)
    failures, _ = _source_report(source)
    source_size_failure = next(
        (failure for failure in failures if failure["gate"] == "source_size"), None
    )

    assert len(source.encode("utf-8")) == MAX_SOURCE_BYTES + delta
    assert (source_size_failure is not None) is exceeds


def test_schema_prompt_and_project_skill_do_not_impose_a_smaller_source_limit():
    from server.verify import MAX_SOURCE_BYTES

    schema = json.loads((ROOT / "server/schemas/module.schema.json").read_text(encoding="utf-8"))
    prompt = (ROOT / "server/prompts/generate_module.md").read_text(encoding="utf-8")
    checklist = (ROOT / ".codex/skills/sim-quality/CHECKLIST.md").read_text(encoding="utf-8")

    assert MAX_SOURCE_BYTES == 96 * 1024
    assert "maxLength" not in schema["properties"]["module_js"]
    assert "96 KiB" in prompt
    assert "UTF-8 bytes" in prompt
    assert "96 KiB" in checklist
    assert "40 KiB" not in checklist
