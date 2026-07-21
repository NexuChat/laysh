from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from server.codex_runtime import StageExecution
from tests.golden_cases import VALID_MODULE_OUTPUT, VALID_UNDERSTANDING

ROOT = Path(__file__).parents[1]
SNAPSHOT = ROOT / "tests" / "snapshots" / "generation-route-shell-ownership.txt"


class CapturingExecutor:
    def __init__(self) -> None:
        self.call: dict[str, object] | None = None

    async def execute_stage(self, **kwargs):
        self.call = kwargs
        return StageExecution(
            data=VALID_MODULE_OUTPUT,
            thread_id="offline-fixture",
            model=kwargs["model"],
            elapsed_ms=0,
        )


@pytest.mark.asyncio
async def test_failed_html_fixture_keeps_shell_owned_and_generation_route_snapshotted():
    from server.codex_backend import CodexBackend
    from server.settings import Settings
    from server.verify import verify_candidate

    executor = CapturingExecutor()
    backend = CodexBackend(executor=executor, settings=Settings())
    await backend.generate(VALID_UNDERSTANDING)

    assert executor.call is not None
    prompt = str(executor.call["prompt"])
    route_snapshot = json.dumps(
        {
            "model": executor.call["model"],
            "effort": executor.call["effort"],
            "schema": Path(executor.call["schema_path"]).name,
            "ownership_clause": " ".join(prompt.splitlines()[:2]),
            "trusted_shell_source": "sim_shell/shell.html",
            "rendered_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        },
        indent=2,
    ) + "\n"
    assert route_snapshot == SNAPSHOT.read_text(encoding="utf-8")

    failed_document = {
        **VALID_MODULE_OUTPUT,
        "module_js": (
            "<!doctype html><html><script>"
            "window.LayshSimulation={};"
            "</script></html>"
        ),
    }
    result = verify_candidate(failed_document, VALID_UNDERSTANDING)
    security_failure = next(
        failure
        for failure in result.failures
        if failure["gate"] == "security"
        and failure["code"] == "forbidden_capability"
    )

    assert result.passed is False
    assert result.artifact is None
    assert "html_document" in security_failure["actual"]["capabilities"]
    assert "no Markdown, full HTML, CSS, or shell UI" in prompt
    assert json.loads(prompt.split("UNDERSTANDING_JSON:\n", 1)[1]) == VALID_UNDERSTANDING
    assert "<!doctype html>" in (ROOT / "sim_shell" / "shell.html").read_text(
        encoding="utf-8"
    ).lower()
