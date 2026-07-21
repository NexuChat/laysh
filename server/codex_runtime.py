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
MAX_VISUAL_EVIDENCE_IMAGE_BYTES = 5 * 1024 * 1024
FORBIDDEN_OUTPUT_SCHEMA_KEYWORDS = frozenset(
    {
        "oneOf",
        "if",
        "then",
        "patternProperties",
        "unevaluatedProperties",
        "format",
        "uniqueItems",
    }
)


def find_forbidden_schema_keywords(value: Any) -> list[str]:
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            found.update(FORBIDDEN_OUTPUT_SCHEMA_KEYWORDS.intersection(node))
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return sorted(found)


def validate_strict_output_schema(schema: Any) -> list[str]:
    """Validate the restricted JSON Schema subset accepted by Codex structured output."""

    violations: list[str] = []

    def walk(node: Any, path: str) -> None:
        if not isinstance(node, dict):
            violations.append(f"{path}:subschema_must_be_object")
            return

        for keyword in sorted(FORBIDDEN_OUTPUT_SCHEMA_KEYWORDS.intersection(node)):
            violations.append(f"{path}:forbidden_keyword:{keyword}")
        if "$ref" in node and len(node) > 1:
            violations.append(f"{path}:ref_cannot_have_sibling_keywords")
        if "type" not in node:
            violations.append(f"{path}:missing_type")

        declared_type = node.get("type")
        declared_types = (
            set(declared_type) if isinstance(declared_type, list) else {declared_type}
        )
        properties = node.get("properties")
        if "object" in declared_types and isinstance(properties, dict):
            if node.get("additionalProperties") is not False:
                violations.append(f"{path}:object_must_set_additionalProperties_false")
            required = node.get("required")
            if not isinstance(required, list) or set(required) != set(properties):
                violations.append(f"{path}:required_must_list_every_property")
        enum = node.get("enum")
        if isinstance(enum, list) and any(isinstance(value, str) for value in enum):
            if "string" not in declared_types:
                violations.append(f"{path}:string_enum_must_have_string_type")

        if isinstance(properties, dict):
            for name, child in properties.items():
                walk(child, f"{path}.properties.{name}")
        definitions = node.get("$defs")
        if isinstance(definitions, dict):
            for name, child in definitions.items():
                walk(child, f"{path}.$defs.{name}")
        for keyword in ("anyOf", "allOf"):
            branches = node.get(keyword)
            if isinstance(branches, list):
                for index, child in enumerate(branches):
                    walk(child, f"{path}.{keyword}[{index}]")
        if "items" in node:
            walk(node["items"], f"{path}.items")

    walk(schema, "$")
    return violations


class CodexRuntimeError(RuntimeError):
    """A sanitized runtime failure safe to use in internal stage control flow."""

    def __init__(
        self,
        code: str,
        *,
        builder_detail: str | None = None,
        safe_detail: dict[str, str | int | None] | None = None,
    ):
        self.code = code
        self.builder_detail = builder_detail
        self.safe_detail = safe_detail or {"kind": "runtime_error"}
        super().__init__(code)


class CodexPolicyError(CodexRuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StageExecution:
    data: dict[str, Any]
    thread_id: str | None
    model: str
    elapsed_ms: int
    attempted_models: tuple[str, ...] = ()
    prior_failure_codes: tuple[str, ...] = ()


class CodexExecutor:
    def __init__(
        self,
        *,
        process_factory: ProcessFactory | None = None,
        codex_path: str | None = None,
        stage_timeout_seconds: float = 90,
        evidence_stage_timeout_seconds: float | None = None,
        record_runtime: bool = False,
        evidence_allowlist: frozenset[str] = frozenset(),
        evidence_image_roots: tuple[Path, ...] = (),
    ) -> None:
        self.process_factory = process_factory or asyncio.create_subprocess_exec
        self.codex_path = codex_path or shutil.which("codex") or "/home/dev/bin/codex"
        self.stage_timeout_seconds = stage_timeout_seconds
        self.evidence_stage_timeout_seconds = (
            stage_timeout_seconds
            if evidence_stage_timeout_seconds is None
            else evidence_stage_timeout_seconds
        )
        self.record_runtime = record_runtime
        self.evidence_allowlist = evidence_allowlist
        self.evidence_image_roots = tuple(root.resolve() for root in evidence_image_roots)

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

    def _validated_image_paths(
        self,
        image_paths: tuple[Path, ...],
        *,
        public: bool,
    ) -> tuple[Path, ...]:
        if not image_paths:
            return ()
        if public:
            raise CodexPolicyError("visual_evidence_curated_only")
        if len(image_paths) != 3:
            raise CodexPolicyError("visual_evidence_image_count")
        resolved: list[Path] = []
        for path in image_paths:
            candidate = path.resolve()
            if not any(candidate.is_relative_to(root) for root in self.evidence_image_roots):
                raise CodexPolicyError("visual_evidence_path_not_allowlisted")
            if candidate.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                raise CodexPolicyError("visual_evidence_type_not_allowed")
            try:
                image_size = candidate.stat().st_size
            except OSError as error:
                raise CodexPolicyError("visual_evidence_unavailable") from error
            if image_size <= 0 or image_size > MAX_VISUAL_EVIDENCE_IMAGE_BYTES:
                raise CodexPolicyError("visual_evidence_size_out_of_bounds")
            resolved.append(candidate)
        return tuple(resolved)

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
    def _builder_stream_detail(stdout: bytes, stderr: bytes) -> str | None:
        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        if stdout_text and stderr_text:
            return f"[stdout]\n{stdout_text}\n[stderr]\n{stderr_text}"[:20_000]
        return (stdout_text or stderr_text)[:20_000] or None

    @staticmethod
    def _safe_upstream_detail(stdout: bytes, returncode: int | None) -> dict[str, str | int | None]:
        """Extract only non-content upstream classification from Codex JSONL."""

        def decoded(value: Any) -> Any:
            if not isinstance(value, str):
                return value
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None

        for raw_line in stdout.decode("utf-8", errors="replace").splitlines():
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            for candidate in (decoded(event.get("message")), event.get("error")):
                if not isinstance(candidate, dict):
                    continue
                nested = candidate.get("error")
                error = nested if isinstance(nested, dict) else candidate
                error_type = error.get("type")
                error_code = error.get("code")
                status = candidate.get("status", error.get("status"))
                if any(value is not None for value in (error_type, error_code, status)):
                    return {
                        "kind": "upstream_error",
                        "type": error_type if isinstance(error_type, str) else None,
                        "code": error_code if isinstance(error_code, str) else None,
                        "status": status if isinstance(status, int) else None,
                    }
        return {"kind": "process_exit", "returncode": returncode}

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
            if event.get("type") in {"error", "turn.failed"}:
                raise CodexRuntimeError("upstream_error", builder_detail=raw_line[:20_000])
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
        timeout_seconds: float | None = None,
        image_paths: tuple[Path, ...] = (),
    ) -> StageExecution:
        try:
            output_schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CodexPolicyError("invalid_local_output_schema") from error
        forbidden_keywords = find_forbidden_schema_keywords(output_schema)
        if forbidden_keywords:
            raise CodexPolicyError(
                f"unsupported_output_schema_keyword:{forbidden_keywords[0]}"
            )
        strict_violations = validate_strict_output_schema(output_schema)
        if strict_violations:
            raise CodexPolicyError(f"incompatible_output_schema:{strict_violations[0]}")
        self._enforce_policy(
            model=model,
            effort=effort,
            public=public,
            evidence_fixture_id=evidence_fixture_id,
        )
        validated_images = self._validated_image_paths(image_paths, public=public)
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
            if validated_images:
                args.extend(["--image", *(str(path) for path in validated_images)])
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
                stage_timeout = timeout_seconds or (
                    self.stage_timeout_seconds if public else self.evidence_stage_timeout_seconds
                )
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(prompt.encode("utf-8")),
                    timeout=stage_timeout,
                )
            except TimeoutError as error:
                await self._terminate_process_group(process)
                raise CodexRuntimeError("stage_timeout") from error
            except asyncio.CancelledError:
                await self._terminate_process_group(process)
                raise
            if process.returncode != 0:
                detail = self._builder_stream_detail(stdout, stderr) if not public else None
                raise CodexRuntimeError(
                    "nonzero_exit",
                    builder_detail=detail,
                    safe_detail=self._safe_upstream_detail(stdout, process.returncode),
                )
        try:
            data, thread_id = self._parse_output(stdout, schema_path)
        except CodexRuntimeError as error:
            if error.safe_detail == {"kind": "runtime_error"}:
                error.safe_detail = self._safe_upstream_detail(stdout, process.returncode)
            if not public:
                error.builder_detail = self._builder_stream_detail(stdout, stderr)
            else:
                error.builder_detail = None
            raise
        return StageExecution(
            data=data,
            thread_id=thread_id,
            model=model,
            elapsed_ms=max(0, int((time.monotonic() - started) * 1000)),
        )
