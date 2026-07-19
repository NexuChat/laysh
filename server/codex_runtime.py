from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import ValidationError

from server.schemas import validate_document
from server.settings import ALLOWED_RUNTIME_MODELS

ProcessFactory = Callable[..., Awaitable[asyncio.subprocess.Process]]
ALLOWED_EFFORTS = frozenset({"low", "medium", "high"})
ENV_ALLOWLIST = (
    "PATH",
    "HOME",
    "CODEX_HOME",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "HTTPS_PROXY",
    "NO_PROXY",
)


class CodexRuntimeError(RuntimeError):
    """A sanitized runtime failure safe to use in internal stage control flow."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class CodexPolicyError(CodexRuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StageExecution:
    data: dict[str, Any]
    thread_id: str | None
    model: str
    elapsed_ms: int


class CodexExecutor:
    def __init__(
        self,
        *,
        process_factory: ProcessFactory | None = None,
        codex_path: str | None = None,
        stage_timeout_seconds: float = 90,
        record_runtime: bool = False,
        evidence_allowlist: frozenset[str] = frozenset(),
    ) -> None:
        self.process_factory = process_factory or asyncio.create_subprocess_exec
        self.codex_path = codex_path or shutil.which("codex") or "/home/dev/bin/codex"
        self.stage_timeout_seconds = stage_timeout_seconds
        self.record_runtime = record_runtime
        self.evidence_allowlist = evidence_allowlist

    def _enforce_policy(
        self,
        *,
        model: str,
        effort: str,
        public: bool,
        evidence_fixture_id: str | None,
    ) -> None:
        if model not in ALLOWED_RUNTIME_MODELS:
            raise CodexPolicyError("model_not_approved_gpt_5_6")
        if effort not in ALLOWED_EFFORTS:
            raise CodexPolicyError("effort_not_allowed")
        if public:
            return
        if not self.record_runtime:
            raise CodexPolicyError("evidence_mode_disabled")
        if evidence_fixture_id not in self.evidence_allowlist:
            raise CodexPolicyError("fixture_not_allowlisted")

    @staticmethod
    def _minimal_environment() -> dict[str, str]:
        return {key: os.environ[key] for key in ENV_ALLOWLIST if key in os.environ}

    @staticmethod
    async def _terminate_process_group(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=1)
        except TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
            await process.wait()

    @staticmethod
    def _parse_output(stdout: bytes, schema_path: Path) -> tuple[dict[str, Any], str | None]:
        thread_id = None
        final_text = None
        for raw_line in stdout.decode("utf-8", errors="replace").splitlines():
            if not raw_line.strip():
                continue
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError as error:
                raise CodexRuntimeError("malformed_jsonl") from error
            if event.get("type") == "thread.started":
                candidate = event.get("thread_id")
                thread_id = candidate if isinstance(candidate, str) else None
            item = event.get("item", {})
            if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                candidate = item.get("text")
                if isinstance(candidate, str):
                    final_text = candidate
        if final_text is None:
            raise CodexRuntimeError("missing_final_message")
        try:
            document = json.loads(final_text)
        except json.JSONDecodeError as error:
            raise CodexRuntimeError("malformed_final_message") from error
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            validate_document(document, schema)
        except (ValidationError, OSError, json.JSONDecodeError) as error:
            raise CodexRuntimeError("schema_validation_failed") from error
        return document, thread_id

    async def execute_stage(
        self,
        *,
        prompt: str,
        schema_path: Path,
        model: str,
        effort: str,
        public: bool = True,
        evidence_fixture_id: str | None = None,
    ) -> StageExecution:
        self._enforce_policy(
            model=model,
            effort=effort,
            public=public,
            evidence_fixture_id=evidence_fixture_id,
        )
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="laysh-codex-") as runtime_directory:
            args = [
                self.codex_path,
                "exec",
                "-",
                "--json",
                "--output-schema",
                str(schema_path),
                "--model",
                model,
                "-c",
                f'model_reasoning_effort="{effort}"',
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--ignore-user-config",
                "--ignore-rules",
                "--cd",
                runtime_directory,
            ]
            if public:
                args.append("--ephemeral")
            try:
                process = await self.process_factory(
                    *args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=runtime_directory,
                    env=self._minimal_environment(),
                    start_new_session=True,
                )
            except (OSError, ValueError) as error:
                raise CodexRuntimeError("spawn_failed") from error
            try:
                stdout, _stderr = await asyncio.wait_for(
                    process.communicate(prompt.encode("utf-8")),
                    timeout=self.stage_timeout_seconds,
                )
            except TimeoutError as error:
                await self._terminate_process_group(process)
                raise CodexRuntimeError("stage_timeout") from error
            except asyncio.CancelledError:
                await self._terminate_process_group(process)
                raise
            if process.returncode != 0:
                raise CodexRuntimeError("nonzero_exit")
        data, thread_id = self._parse_output(stdout, schema_path)
        return StageExecution(
            data=data,
            thread_id=thread_id,
            model=model,
            elapsed_ms=max(0, int((time.monotonic() - started) * 1000)),
        )
