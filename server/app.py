from __future__ import annotations

import hashlib
import json
import os
import secrets
import unicodedata
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from server.assemble import PORTABLE_CSP
from server.browser_verify import BrowserVerificationResult, verify_artifact_in_browser
from server.cache import VERIFIED_CACHE_CONTRACT_VERSION, VerifiedCache
from server.codex_backend import CodexBackend, MockCodexBackend
from server.codex_runtime import CodexExecutor
from server.goldens import (
    GOLDEN_FIXTURE_IDS,
    GOLDEN_ROOT,
    list_pinned_goldens,
    load_pinned_golden,
    localized_pinned_golden,
)
from server.jobs import TERMINAL_STATES, JobManager
from server.model_lab import (
    ModelLabAccepted,
    ModelLabCompareRequest,
    ModelLabManager,
    ModelLabPipelineRequest,
    ModelLabPipelineRerunRequest,
    ModelLabPipelineRunResult,
    ModelLabRunResult,
)
from server.model_lab_discovery import WikimediaEvidenceProvider
from server.ratelimit import GenerationLimiter
from server.schemas import AskAccepted, AskRequest, PublicResult
from server.settings import Settings
from server.share_store import (
    DEFAULT_SHARE_RETENTION_SECONDS,
    ShareLink,
    ShareStore,
)
from server.static_assets import StaticAssetVersionMiddleware

ROOT = Path(__file__).parents[1]
EMBED_BRIDGE_MARKER = "data-laysh-embed-bridge"
CURATED_GOLDEN_CACHE_CONTRACT_VERSION = "1.0"


def _artifact_for_embed(artifact: str) -> str:
    if EMBED_BRIDGE_MARKER in artifact:
        return artifact
    bridge = (ROOT / "sim_shell" / "embed_bridge.js").read_text(encoding="utf-8")
    closing_body = "</body>"
    if closing_body not in artifact:
        raise ValueError("verified artifact has no closing body element")
    return artifact.replace(
        closing_body,
        f'<script {EMBED_BRIDGE_MARKER}>{bridge}</script>{closing_body}',
        1,
    )


def create_app(
    backend: MockCodexBackend | CodexBackend | None = None,
    model_lab_backend: MockCodexBackend | CodexBackend | None = None,
    model_lab_evidence_provider: object | None = None,
    job_timeout_seconds: float | None = None,
    browser_verifier: Callable[[str], BrowserVerificationResult] = verify_artifact_in_browser,
    share_root: Path | None = None,
    share_retention_seconds: int = DEFAULT_SHARE_RETENTION_SECONDS,
    share_clock: Callable[[], float] | None = None,
) -> FastAPI:
    settings = Settings.from_env()

    def configured_codex_backend() -> CodexBackend:
        return CodexBackend(
            executor=CodexExecutor(
                stage_timeout_seconds=settings.public_stage_timeout_seconds,
                evidence_stage_timeout_seconds=settings.evidence_stage_timeout_seconds,
                record_runtime=settings.record_runtime,
                evidence_allowlist=frozenset(GOLDEN_FIXTURE_IDS),
            ),
            settings=settings,
        )

    if backend is not None:
        selected_backend = backend
    elif settings.backend == "codex":
        selected_backend = configured_codex_backend()
    else:
        selected_backend = MockCodexBackend()
    selected_model_lab_backend = model_lab_backend
    if selected_model_lab_backend is None:
        selected_model_lab_backend = (
            configured_codex_backend()
            if settings.model_lab_enabled and settings.backend == "codex"
            else selected_backend
        )
    public_timeout = (
        settings.public_job_timeout_seconds if job_timeout_seconds is None else job_timeout_seconds
    )
    app = FastAPI(title="Laysh", version="1.1.0")
    app.add_middleware(StaticAssetVersionMiddleware)
    app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
    verified_cache = (
        VerifiedCache(
            root=ROOT / "out" / "cache" / "live",
            golden_root=GOLDEN_ROOT,
            secret=settings.cache_key_secret.encode(),
            contract_version=VERIFIED_CACHE_CONTRACT_VERSION,
            curated_legacy_goldens={
                fixture_id.removesuffix("_ar"): CURATED_GOLDEN_CACHE_CONTRACT_VERSION
                for fixture_id in GOLDEN_FIXTURE_IDS
            },
        )
        if settings.cache_key_secret
        else None
    )
    app.state.jobs = JobManager(
        selected_backend,
        public_job_timeout_seconds=public_timeout,
        evidence_job_timeout_seconds=settings.evidence_job_timeout_seconds,
        browser_verifier=browser_verifier,
        cache=verified_cache,
        max_concurrent_jobs=settings.max_concurrent_jobs,
        max_queued_jobs=settings.max_queued_jobs,
    )
    configured_share_root = os.getenv("LAYSH_SHARE_ROOT")
    selected_share_root = (
        share_root
        or (Path(configured_share_root) if configured_share_root else None)
        or ROOT / "out" / "cache" / "live" / "shares"
    )
    share_store_options = {
        "root": selected_share_root,
        "retention_seconds": share_retention_seconds,
    }
    if share_clock is not None:
        share_store_options["clock"] = share_clock
    app.state.share_store = ShareStore(**share_store_options)
    app.state.share_candidates = {}
    limiter_secret = (
        settings.rate_limit_key_secret.encode()
        if settings.rate_limit_key_secret
        else secrets.token_bytes(32)
    )
    app.state.generation_limiter = GenerationLimiter(
        secret=limiter_secret,
        per_ip_per_hour=settings.ip_generations_per_hour,
        global_per_day=settings.global_generations_per_day,
    )
    app.state.model_lab = ModelLabManager(
        backend=selected_model_lab_backend,
        browser_verifier=browser_verifier,
        evidence_provider=(
            model_lab_evidence_provider or WikimediaEvidenceProvider()
        ),
        max_concurrent_runs=settings.model_lab_max_concurrent_runs,
    )
    app.state.model_lab_limiter = GenerationLimiter(
        secret=hashlib.sha256(limiter_secret + b":model-lab").digest(),
        per_ip_per_hour=settings.model_lab_ip_comparisons_per_hour,
        global_per_day=settings.model_lab_global_comparisons_per_day,
    )
    app.add_event_handler("shutdown", app.state.model_lab.cancel_all)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        content = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(
            content,
            headers={
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
            },
        )

    @app.post("/api/ask", response_model=AskAccepted, status_code=status.HTTP_202_ACCEPTED)
    async def ask(payload: AskRequest, request: Request) -> AskAccepted:
        question = unicodedata.normalize("NFKC", payload.question).strip()
        if not question:
            raise HTTPException(status_code=422, detail="question must not be blank")
        if not app.state.jobs.has_capacity():
            record = app.state.jobs.start_capacity_fallback(payload.locale, "queue_full")
        else:
            client_ip = request.client.host if request.client else "unknown"
            limit_reason = app.state.generation_limiter.acquire(client_ip)
            record = (
                app.state.jobs.start_capacity_fallback(payload.locale, limit_reason)
                if limit_reason
                else app.state.jobs.start(
                    question,
                    payload.locale,
                    fresh_generation=payload.generation_mode == "fresh",
                )
            )
        return AskAccepted(
            job_id=record.job_id,
            stream_url=f"/api/jobs/{record.job_id}/events",
            result_url=f"/api/jobs/{record.job_id}",
        )

    def require_model_lab() -> None:
        if not settings.model_lab_enabled:
            raise HTTPException(status_code=404, detail="not found")

    @app.get("/model-lab", response_class=HTMLResponse)
    async def model_lab_page() -> HTMLResponse:
        require_model_lab()
        content = (ROOT / "web" / "model-lab.html").read_text(encoding="utf-8")
        return HTMLResponse(
            content,
            headers={
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
                "X-Robots-Tag": "noindex, nofollow",
            },
        )

    @app.post(
        "/api/model-lab/pipeline",
        response_model=ModelLabAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def start_model_lab_pipeline(
        payload: ModelLabPipelineRequest,
        request: Request,
    ) -> ModelLabAccepted:
        require_model_lab()
        question = unicodedata.normalize("NFKC", payload.question).strip()
        if not question:
            raise HTTPException(status_code=422, detail="question must not be blank")
        client_ip = request.client.host if request.client else "unknown"
        if app.state.model_lab_limiter.acquire(client_ip):
            raise HTTPException(status_code=429, detail="model lab pipeline limit reached")
        return app.state.model_lab.start_pipeline(
            payload.model_copy(update={"question": question})
        )

    @app.get(
        "/api/model-lab/pipeline/{run_id}",
        response_model=ModelLabPipelineRunResult,
    )
    async def get_model_lab_pipeline(
        run_id: str,
        response: Response,
    ) -> ModelLabPipelineRunResult:
        require_model_lab()
        response.headers["Cache-Control"] = "no-store"
        run = app.state.model_lab.get_pipeline(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="model lab pipeline not found")
        return run

    @app.post(
        "/api/model-lab/pipeline/{run_id}/rerun",
        response_model=ModelLabAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def rerun_model_lab_pipeline(
        run_id: str,
        payload: ModelLabPipelineRerunRequest,
    ) -> ModelLabAccepted:
        require_model_lab()
        try:
            return app.state.model_lab.rerun_pipeline(run_id, payload)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail="model lab pipeline not found",
            ) from error
        except RuntimeError as error:
            raise HTTPException(
                status_code=409,
                detail="model lab pipeline is already running",
            ) from error

    @app.post(
        "/api/model-lab/pipeline/{run_id}/cancel",
        response_model=ModelLabPipelineRunResult,
    )
    async def cancel_model_lab_pipeline(
        run_id: str,
    ) -> ModelLabPipelineRunResult:
        require_model_lab()
        try:
            return await app.state.model_lab.cancel_pipeline(run_id)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail="model lab pipeline not found",
            ) from error

    @app.post(
        "/api/model-lab/compare",
        response_model=ModelLabAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def compare_models(
        payload: ModelLabCompareRequest,
        request: Request,
    ) -> ModelLabAccepted:
        require_model_lab()
        question = unicodedata.normalize("NFKC", payload.question).strip()
        if not question:
            raise HTTPException(status_code=422, detail="question must not be blank")
        client_ip = request.client.host if request.client else "unknown"
        if app.state.model_lab_limiter.acquire(client_ip):
            raise HTTPException(status_code=429, detail="model lab comparison limit reached")
        return app.state.model_lab.start(payload.model_copy(update={"question": question}))

    @app.get(
        "/api/model-lab/runs/{run_id}",
        response_model=ModelLabRunResult,
    )
    async def get_model_lab_run(run_id: str, response: Response) -> ModelLabRunResult:
        require_model_lab()
        response.headers["Cache-Control"] = "no-store"
        run = app.state.model_lab.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="model lab run not found")
        return run

    @app.get("/api/model-lab/artifacts/{artifact_id}")
    async def get_model_lab_artifact(artifact_id: str) -> Response:
        require_model_lab()
        artifact = app.state.model_lab.artifacts.get(artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="model lab artifact not found")
        return HTMLResponse(
            _artifact_for_embed(artifact),
            headers={
                "Content-Disposition": f'inline; filename="laysh-{artifact_id}.html"',
                "Content-Security-Policy": PORTABLE_CSP,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
            },
        )

    @app.get("/api/jobs/{job_id}", response_model=PublicResult)
    async def get_job(job_id: str) -> PublicResult:
        record = app.state.jobs.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        return record.public_result()

    @app.get("/api/jobs/{job_id}/events")
    async def get_events(
        job_id: str,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        record = app.state.jobs.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        try:
            cursor = max(0, int(last_event_id or "0"))
        except ValueError:
            cursor = 0

        async def event_stream():
            nonlocal cursor
            while True:
                pending = [event for event in record.events if event.id > cursor]
                for event in pending:
                    cursor = event.id
                    data = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
                    yield f"id: {event.id}\nevent: {event.type}\ndata: {data}\n\n"
                if record.status in TERMINAL_STATES:
                    break
                await __import__("asyncio").sleep(0.01)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/jobs/{job_id}/cancel", response_model=PublicResult)
    async def cancel_job(job_id: str) -> PublicResult:
        record = app.state.jobs.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        return await app.state.jobs.cancel(record)

    @app.get("/api/gallery")
    async def gallery(locale: str = Query(default="ar", pattern="^(ar|en)$")) -> dict:
        lessons = []
        for document in list_pinned_goldens():
            selected = document["metadata"][locale]
            lessons.append(
                {
                    "id": document["golden_id"],
                    "title": selected["title"],
                    "domain": selected["domain"],
                    "summary": selected["summary"],
                    "instant": True,
                    "tier": "A",
                }
            )
        return {
            "contract_version": "1.0",
            "lessons": lessons,
        }

    @app.get("/api/gallery/{golden_id}")
    async def gallery_lesson(
        golden_id: str,
        locale: str = Query(default="ar", pattern="^(ar|en)$"),
    ) -> dict:
        document = load_pinned_golden(golden_id)
        if document is None:
            raise HTTPException(status_code=404, detail="golden lesson not found")
        localized = localized_pinned_golden(document, locale)
        sim_id = "golden_" + hashlib.sha256(localized["artifact"].encode()).hexdigest()[:16]
        app.state.jobs.artifacts[sim_id] = localized["artifact"]
        app.state.share_candidates[sim_id] = {
            "title": localized["title"],
            "lang": localized["lang"],
            "direction": localized["direction"],
            "tier": "A",
        }
        return {
            "contract_version": "1.0",
            "id": golden_id,
            "answer": localized["answer"],
            "simulation": {
                "sim_id": sim_id,
                "title": localized["title"],
                "lang": localized["lang"],
                "direction": localized["direction"],
                "artifact_url": f"/api/sims/{sim_id}/download",
                "tier": "A",
                "effective_model": "verified/golden",
                "elapsed_ms": 0,
                "check_count": document["receipt"]["check_count"],
                "heal_count": document["evidence"].get("heal_count", 0),
            },
        }

    @app.get("/api/sims/{sim_id}/download")
    async def download_sim(sim_id: str, inline: bool = Query(default=False)) -> Response:
        artifact = app.state.jobs.artifacts.get(sim_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="simulation not found")
        disposition = "inline" if inline else "attachment"
        delivered_artifact = _artifact_for_embed(artifact) if inline else artifact
        return HTMLResponse(
            delivered_artifact,
            headers={
                "Content-Disposition": f'{disposition}; filename="laysh-{sim_id}.html"',
                "Content-Security-Policy": PORTABLE_CSP,
                "X-Content-Type-Options": "nosniff",
            },
        )

    def eligible_share_candidate(sim_id: str) -> dict | None:
        if sim_id not in app.state.jobs.artifacts:
            return None
        for record in app.state.jobs.records.values():
            simulation = record.simulation
            if (
                record.status == "complete"
                and simulation is not None
                and simulation.sim_id == sim_id
                and simulation.tier in {"A", "B"}
                and record.share_eligible
            ):
                return {
                    "title": simulation.title,
                    "lang": simulation.lang,
                    "direction": simulation.direction,
                    "tier": simulation.tier,
                }
        candidate = app.state.share_candidates.get(sim_id)
        return candidate if isinstance(candidate, dict) else None

    @app.post(
        "/api/sims/{sim_id}/share",
        response_model=ShareLink,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_share(sim_id: str, response: Response) -> ShareLink:
        response.headers["Cache-Control"] = "no-store"
        metadata = eligible_share_candidate(sim_id)
        if metadata is None:
            raise HTTPException(
                status_code=404,
                detail="simulation unavailable",
                headers={"Cache-Control": "no-store"},
            )
        artifact = app.state.jobs.artifacts[sim_id]
        try:
            shared = app.state.share_store.create(artifact=artifact, **metadata)
        except (OSError, ValueError):
            raise HTTPException(
                status_code=503,
                detail="share unavailable",
                headers={"Cache-Control": "no-store"},
            ) from None
        return shared.public_link()

    @app.post("/api/sims/{invalid_path:path}/share", include_in_schema=False)
    async def reject_invalid_simulation_share(invalid_path: str) -> None:
        del invalid_path
        raise HTTPException(
            status_code=404,
            detail="simulation unavailable",
            headers={"Cache-Control": "no-store"},
        )

    def resolve_share(share_id: str):
        try:
            shared = app.state.share_store.resolve(share_id)
        except (OSError, ValueError):
            shared = None
        if shared is None:
            raise HTTPException(
                status_code=404,
                detail="share unavailable",
                headers={"Cache-Control": "no-store"},
            )
        return shared

    @app.get("/api/shares/{share_id}", response_model=ShareLink)
    async def share_metadata(share_id: str, response: Response) -> ShareLink:
        response.headers["Cache-Control"] = "no-store"
        return resolve_share(share_id).public_link()

    @app.get("/api/shares/{share_id}/download")
    async def download_share(share_id: str) -> Response:
        shared = resolve_share(share_id)
        return HTMLResponse(
            shared.artifact,
            headers={
                "Content-Disposition": f'attachment; filename="laysh-{share_id}.html"',
                "Content-Security-Policy": PORTABLE_CSP,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
            },
        )

    @app.get("/api/shares/{invalid_path:path}", include_in_schema=False)
    async def reject_invalid_share_path(invalid_path: str) -> None:
        del invalid_path
        raise HTTPException(
            status_code=404,
            detail="share unavailable",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/s/{share_id}")
    async def play_share(share_id: str) -> Response:
        try:
            shared = app.state.share_store.resolve(share_id)
        except (OSError, ValueError):
            shared = None
        if shared is None:
            return RedirectResponse(
                url="/#gallery",
                status_code=status.HTTP_303_SEE_OTHER,
                headers={"Cache-Control": "no-store"},
            )
        return HTMLResponse(
            shared.artifact,
            headers={
                "Content-Disposition": f'inline; filename="laysh-{share_id}.html"',
                "Content-Security-Policy": PORTABLE_CSP,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
            },
        )

    @app.get("/s/{invalid_path:path}", include_in_schema=False)
    async def redirect_invalid_share_path(invalid_path: str) -> Response:
        del invalid_path
        return RedirectResponse(
            url="/#gallery",
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/healthz")
    async def health() -> dict:
        return {
            "status": "ok",
            "backend": selected_backend.backend_name,
            "queue": {
                "active": app.state.jobs.active_count,
                "known_jobs": len(app.state.jobs.records),
            },
            "config": {
                "generation_strategy": settings.public_generation_strategy,
                "heal_attempt_limit": settings.public_heal_attempt_limit,
                "public_job_timeout_seconds": settings.public_job_timeout_seconds,
                "public_stage_timeout_seconds": settings.public_stage_timeout_seconds,
                "public_qa_timeout_seconds": settings.public_qa_timeout_seconds,
                "models": {
                    "understand": settings.understand_model,
                    "generate": (
                        settings.public_generate_model_override
                        or settings.generate_model
                    ),
                    "physics": settings.physics_model,
                    "visual": settings.visual_model,
                    "heal": settings.heal_model,
                    "qa": settings.qa_model,
                },
            },
        }

    return app


app = create_app()
