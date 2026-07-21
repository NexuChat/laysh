from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).parents[1]
SYSTEMCTL = "/usr/bin/systemctl"
GIT = "/usr/bin/git"
MAIN_SERVICE = "laysh.service"
HEALTH_SERVICE = "laysh-healthcheck.service"
HEALTH_TIMER = "laysh-healthcheck.timer"
DEFAULT_PORT = 8765
COMMAND_TIMEOUT_SECONDS = 10
HTTP_TIMEOUT_SECONDS = 5
MAX_RESPONSE_BYTES = 1024 * 1024
SERVICE_SHOW_PROPERTIES = (
    "Id",
    "LoadState",
    "ActiveState",
    "SubState",
    "UnitFileState",
    "Result",
    "ExecMainStatus",
    "WorkingDirectory",
    "ExecStart",
)
TIMER_SHOW_PROPERTIES = (
    "Id",
    "LoadState",
    "ActiveState",
    "SubState",
    "UnitFileState",
    "Result",
)

RunCommand = Callable[..., subprocess.CompletedProcess[str]]
OpenUrl = Callable[..., Any]
Now = Callable[[], datetime]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
CommitHash = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ClosedReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CommandReceipt(ClosedReceipt):
    argv: list[str] = Field(min_length=4, max_length=8)
    exit_code: int
    stdout: str
    stdout_sha256: Sha256
    stderr: str
    stderr_sha256: Sha256

    @model_validator(mode="after")
    def bind_stream_hashes(self) -> CommandReceipt:
        if _sha256(self.stdout) != self.stdout_sha256:
            raise ValueError("command stdout hash does not match the captured bytes")
        if _sha256(self.stderr) != self.stderr_sha256:
            raise ValueError("command stderr hash does not match the captured bytes")
        return self


class HealthCommands(ClosedReceipt):
    service_is_active: CommandReceipt
    service_show: CommandReceipt
    health_timer_is_active: CommandReceipt
    health_timer_show: CommandReceipt
    health_service_is_active: CommandReceipt
    health_service_show: CommandReceipt


class HttpReceipt(ClosedReceipt):
    method: Literal["GET"]
    url: str = Field(min_length=1, max_length=200)
    status: int = Field(ge=100, le=599)
    body: str = Field(max_length=MAX_RESPONSE_BYTES)
    body_sha256: Sha256
    request_command: list[str] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def bind_request_and_body(self) -> HttpReceipt:
        if self.request_command != [self.method, self.url]:
            raise ValueError("HTTP request command must bind the exact method and URL")
        if _sha256(self.body) != self.body_sha256:
            raise ValueError("HTTP body hash does not match the captured bytes")
        return self


class HealthReceipt(ClosedReceipt):
    schema_version: Literal["1.0"]
    gate: Literal["service"]
    captured_at_utc: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T.*Z$")
    commit: CommitHash
    commands: HealthCommands
    http: HttpReceipt

    @model_validator(mode="after")
    def require_operational_raw_evidence(self) -> HealthReceipt:
        commands = self.commands
        _require_is_active(commands.service_is_active, MAIN_SERVICE, active=True)
        _require_is_active(commands.health_timer_is_active, HEALTH_TIMER, active=True)
        _require_is_active(
            commands.health_service_is_active,
            HEALTH_SERVICE,
            active=False,
        )
        service = _require_show(
            commands.service_show,
            MAIN_SERVICE,
            SERVICE_SHOW_PROPERTIES,
        )
        timer = _require_show(
            commands.health_timer_show,
            HEALTH_TIMER,
            TIMER_SHOW_PROPERTIES,
        )
        health_service = _require_show(
            commands.health_service_show,
            HEALTH_SERVICE,
            SERVICE_SHOW_PROPERTIES,
        )
        _require_service_state(service, repository_bound=True)
        if (
            timer["LoadState"] != "loaded"
            or timer["ActiveState"] != "active"
            or timer["SubState"] != "waiting"
            or timer["UnitFileState"] != "enabled"
        ):
            raise ValueError("health timer is not loaded, enabled, active, and waiting")
        if (
            health_service["LoadState"] != "loaded"
            or health_service["Result"] != "success"
            or health_service["ExecMainStatus"] != "0"
        ):
            raise ValueError("latest health service execution did not succeed")
        _require_http_url(self.http, "/healthz")
        if self.http.status != 200:
            raise ValueError("health endpoint did not return HTTP 200")
        body = _json_object(self.http.body, name="health endpoint")
        if body.get("status") != "ok" or body.get("backend") != "codex":
            raise ValueError("health endpoint is not green on the Codex backend")
        return self


class GalleryReceipt(ClosedReceipt):
    schema_version: Literal["1.0"]
    gate: Literal["service_gallery"]
    captured_at_utc: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T.*Z$")
    commit: CommitHash
    http: HttpReceipt

    @model_validator(mode="after")
    def require_six_instant_tier_a_lessons(self) -> GalleryReceipt:
        _require_http_url(self.http, "/api/gallery?locale=ar")
        if self.http.status != 200:
            raise ValueError("gallery endpoint did not return HTTP 200")
        body = _json_object(self.http.body, name="gallery endpoint")
        lessons = body.get("lessons")
        if body.get("contract_version") != "1.0" or not isinstance(lessons, list):
            raise ValueError("gallery body does not expose the versioned lesson list")
        lesson_ids = {
            lesson.get("id")
            for lesson in lessons
            if isinstance(lesson, dict)
            and isinstance(lesson.get("id"), str)
            and lesson.get("id")
            and lesson.get("instant") is True
            and lesson.get("tier") == "A"
        }
        if len(lessons) != 6 or len(lesson_ids) != 6:
            raise ValueError("gallery must contain exactly six unique instant Tier-A cards")
        return self


def _json_object(source: str, *, name: str) -> dict[str, object]:
    try:
        value = json.loads(source)
    except json.JSONDecodeError as error:
        raise ValueError(f"{name} did not return valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{name} JSON must be an object")
    return value


def _show_arguments(unit: str, properties: tuple[str, ...]) -> list[str]:
    return [
        SYSTEMCTL,
        "--user",
        "show",
        unit,
        "--no-pager",
        f"--property={','.join(properties)}",
    ]


def _require_is_active(receipt: CommandReceipt, unit: str, *, active: bool) -> None:
    expected = [SYSTEMCTL, "--user", "is-active", unit]
    if receipt.argv != expected or receipt.stderr:
        raise ValueError(f"{unit} is-active receipt is not the exact clean command")
    if active:
        if receipt.exit_code != 0 or receipt.stdout.strip() != "active":
            raise ValueError(f"{unit} is not active")
    elif receipt.exit_code not in {0, 3} or receipt.stdout.strip() not in {
        "active",
        "inactive",
    }:
        raise ValueError(f"{unit} is-active returned an unexpected state")


def _parse_show(stdout: str) -> dict[str, str]:
    properties: dict[str, str] = {}
    for line in stdout.splitlines():
        key, separator, value = line.partition("=")
        if not separator or not key or key in properties:
            raise ValueError("systemctl show output is ambiguous")
        properties[key] = value
    return properties


def _require_show(
    receipt: CommandReceipt,
    unit: str,
    properties: tuple[str, ...],
) -> dict[str, str]:
    if receipt.argv != _show_arguments(unit, properties):
        raise ValueError(f"{unit} show receipt used an unexpected command")
    if receipt.exit_code != 0 or receipt.stderr:
        raise ValueError(f"{unit} show command did not complete cleanly")
    parsed = _parse_show(receipt.stdout)
    if any(property_name not in parsed for property_name in properties):
        raise ValueError(f"{unit} show output omitted a requested property")
    if parsed["Id"] != unit:
        raise ValueError(f"{unit} show output identifies a different unit")
    return parsed


def _require_service_paths(properties: dict[str, str]) -> None:
    working_directory = properties["WorkingDirectory"]
    exec_start = properties["ExecStart"]
    if not Path(working_directory).is_absolute() or working_directory not in exec_start:
        raise ValueError("service WorkingDirectory and ExecStart are not repository-bound")


def _require_service_state(
    properties: dict[str, str],
    *,
    repository_bound: bool,
) -> None:
    if (
        properties["LoadState"] != "loaded"
        or properties["ActiveState"] != "active"
        or properties["SubState"] != "running"
        or properties["UnitFileState"] != "enabled"
        or properties["Result"] != "success"
        or properties["ExecMainStatus"] != "0"
    ):
        raise ValueError("main service is not loaded, enabled, active, and successful")
    if repository_bound:
        _require_service_paths(properties)


def _require_http_url(receipt: HttpReceipt, path: str) -> None:
    if not re.fullmatch(rf"http://127\.0\.0\.1:[1-9]\d{{0,4}}{re.escape(path)}", receipt.url):
        raise ValueError("release probes may access only the fixed loopback endpoint")
    port = int(receipt.url.split(":", 2)[2].split("/", 1)[0])
    if port > 65535:
        raise ValueError("loopback service port is out of range")


def _run(
    arguments: list[str],
    *,
    run_command: RunCommand,
) -> subprocess.CompletedProcess[str]:
    return run_command(  # noqa: S603
        arguments,
        check=False,
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
        shell=False,
    )


def _command_receipt(
    arguments: list[str],
    *,
    run_command: RunCommand,
) -> dict[str, object]:
    completed = _run(arguments, run_command=run_command)
    return CommandReceipt(
        argv=arguments,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stdout_sha256=_sha256(completed.stdout),
        stderr=completed.stderr,
        stderr_sha256=_sha256(completed.stderr),
    ).model_dump()


def _http_receipt(url: str, *, open_url: OpenUrl) -> dict[str, object]:
    request = Request(  # noqa: S310
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )
    with open_url(request, timeout=HTTP_TIMEOUT_SECONDS) as response:  # noqa: S310
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        status = int(response.status)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("service evidence response exceeds the one MiB safety bound")
    body = raw.decode("utf-8", errors="strict")
    return HttpReceipt(
        method="GET",
        url=url,
        status=status,
        body=body,
        body_sha256=_sha256(body),
        request_command=["GET", url],
    ).model_dump()


def _current_commit(
    repository_root: Path,
    *,
    run_command: RunCommand,
) -> str:
    completed = _run(
        [GIT, "-C", str(repository_root), "rev-parse", "HEAD"],
        run_command=run_command,
    )
    commit = completed.stdout.strip()
    if completed.returncode != 0 or completed.stderr or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("could not bind service evidence to an exact repository commit")
    return commit


def _timestamp(now: Now) -> str:
    captured = now()
    if captured.tzinfo is None:
        raise ValueError("capture clock must return a timezone-aware instant")
    return captured.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def validate_health_receipt(document: object) -> HealthReceipt:
    return HealthReceipt.model_validate(document)


def validate_gallery_receipt(document: object) -> GalleryReceipt:
    return GalleryReceipt.model_validate(document)


def capture_release_service(
    *,
    repository_root: Path = ROOT,
    port: int = DEFAULT_PORT,
    run_command: RunCommand = subprocess.run,
    open_url: OpenUrl = urlopen,
    now: Now = lambda: datetime.now(UTC),
) -> tuple[dict[str, object], dict[str, object]]:
    if not 1 <= port <= 65535:
        raise ValueError("service port must be between 1 and 65535")
    repository_root = repository_root.resolve()
    commit = _current_commit(repository_root, run_command=run_command)
    commands = {
        "service_is_active": _command_receipt(
            [SYSTEMCTL, "--user", "is-active", MAIN_SERVICE],
            run_command=run_command,
        ),
        "service_show": _command_receipt(
            _show_arguments(MAIN_SERVICE, SERVICE_SHOW_PROPERTIES),
            run_command=run_command,
        ),
        "health_timer_is_active": _command_receipt(
            [SYSTEMCTL, "--user", "is-active", HEALTH_TIMER],
            run_command=run_command,
        ),
        "health_timer_show": _command_receipt(
            _show_arguments(HEALTH_TIMER, TIMER_SHOW_PROPERTIES),
            run_command=run_command,
        ),
        "health_service_is_active": _command_receipt(
            [SYSTEMCTL, "--user", "is-active", HEALTH_SERVICE],
            run_command=run_command,
        ),
        "health_service_show": _command_receipt(
            _show_arguments(HEALTH_SERVICE, SERVICE_SHOW_PROPERTIES),
            run_command=run_command,
        ),
    }
    captured_at_utc = _timestamp(now)
    base_url = f"http://127.0.0.1:{port}"
    health = HealthReceipt(
        schema_version="1.0",
        gate="service",
        captured_at_utc=captured_at_utc,
        commit=commit,
        commands=commands,
        http=_http_receipt(f"{base_url}/healthz", open_url=open_url),
    ).model_dump()
    gallery = GalleryReceipt(
        schema_version="1.0",
        gate="service_gallery",
        captured_at_utc=captured_at_utc,
        commit=commit,
        http=_http_receipt(
            f"{base_url}/api/gallery?locale=ar",
            open_url=open_url,
        ),
    ).model_dump()
    return health, gallery


def _write_json_atomic(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def capture_and_write(
    *,
    health_path: Path,
    gallery_path: Path,
    repository_root: Path = ROOT,
    port: int = DEFAULT_PORT,
    run_command: RunCommand = subprocess.run,
    open_url: OpenUrl = urlopen,
    now: Now = lambda: datetime.now(UTC),
) -> tuple[dict[str, object], dict[str, object]]:
    health, gallery = capture_release_service(
        repository_root=repository_root,
        port=port,
        run_command=run_command,
        open_url=open_url,
        now=now,
    )
    _write_json_atomic(health_path, health)
    _write_json_atomic(gallery_path, gallery)
    return health, gallery


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture raw, replayable evidence from the local Laysh user service",
    )
    parser.add_argument(
        "--health-report",
        type=Path,
        default=ROOT / "out/evidence/release-service-health.json",
    )
    parser.add_argument(
        "--gallery-report",
        type=Path,
        default=ROOT / "out/evidence/release-service-gallery.json",
    )
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    arguments = parser.parse_args()
    health, gallery = capture_and_write(
        health_path=arguments.health_report,
        gallery_path=arguments.gallery_report,
        repository_root=arguments.repository_root,
        port=arguments.port,
    )
    print(
        json.dumps(
            {
                "commit": health["commit"],
                "health_body_sha256": health["http"]["body_sha256"],
                "gallery_body_sha256": gallery["http"]["body_sha256"],
                "health_report": str(arguments.health_report),
                "gallery_report": str(arguments.gallery_report),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
