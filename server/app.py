from __future__ import annotations

import json
import re
import secrets
import unicodedata
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from server.assemble import PORTABLE_CSP
from server.browser_verify import BrowserVerificationResult, verify_artifact_in_browser
from server.cache import VerifiedCache
from server.codex_backend import CodexBackend, MockCodexBackend
from server.codex_runtime import CodexExecutor
from server.goldens import GOLDEN_FIXTURE_IDS, GOLDEN_ROOT, list_pinned_goldens, load_pinned_golden
from server.jobs import TERMINAL_STATES, JobManager
from server.ratelimit import GenerationLimiter
from server.schemas import (
    AnswerPayload,
    AskAccepted,
    AskRequest,
    PublicResult,
    SharedSimulation,
    SimulationMetadata,
)
from server.settings import Settings

ROOT = Path(__file__).parents[1]
CACHE_REVALIDATION = "no-cache, must-revalidate"


class RevalidatingStaticFiles(StaticFiles):
    """Serve deployable assets with validators but never as stale cached copies."""

    async def get_response(self, path: str, scope: dict) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = CACHE_REVALIDATION
        return response


def create_app(
    backend: MockCodexBackend | CodexBackend | None = None,
    job_timeout_seconds: float | None = None,
    browser_verifier: Callable[[str], BrowserVerificationResult] = verify_artifact_in_browser,
) -> FastAPI:
    settings = Settings.from_env()
    if backend is not None:
        selected_backend = backend
    elif settings.backend == "codex":
        selected_backend = CodexBackend(
            executor=CodexExecutor(
                stage_timeout_seconds=settings.public_stage_timeout_seconds,
                evidence_stage_timeout_seconds=settings.evidence_stage_timeout_seconds,
                record_runtime=settings.record_runtime,
                evidence_allowlist=frozenset(GOLDEN_FIXTURE_IDS),
            ),
            settings=settings,
        )
    else:
        selected_backend = MockCodexBackend()
    if isinstance(selected_backend, CodexBackend) and not settings.cache_key_secret:
        raise ValueError("LAYSH_CACHE_KEY_SECRET is required for the live Codex backend")
    public_timeout = (
        settings.public_job_timeout_seconds if job_timeout_seconds is None else job_timeout_seconds
    )
    app = FastAPI(title="Laysh", version="1.1.0")
    app.mount("/static", RevalidatingStaticFiles(directory=ROOT / "web"), name="static")
    live_cache_root = (
        Path(settings.live_cache_root)
        if settings.live_cache_root
        else ROOT / "out" / "cache" / "live"
    )
    verified_cache = (
        VerifiedCache(
            root=live_cache_root,
            golden_root=GOLDEN_ROOT,
            secret=settings.cache_key_secret.encode(),
            contract_version="1.0",
            max_live_entries=settings.max_live_lessons,
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
    app.state.verified_cache = verified_cache

    def index_response() -> HTMLResponse:
        content = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(
            content,
            headers={
                "Cache-Control": CACHE_REVALIDATION,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
        )

    def resolve_shareable(sim_id: str) -> tuple[str, SharedSimulation] | None:
        if not re.fullmatch(r"(?:golden_[a-z0-9_]+|[a-f0-9]{24})", sim_id):
            return None
        if sim_id.startswith("golden_"):
            golden_id = sim_id.removeprefix("golden_")
            document = load_pinned_golden(golden_id)
            if document is not None and document.get("cache_id") == sim_id:
                try:
                    answer = AnswerPayload.model_validate(document["answer"])
                except (KeyError, ValueError):
                    return None
                return (
                    document["artifact"],
                    SharedSimulation(
                        answer=answer,
                        simulation=SimulationMetadata(
                            sim_id=sim_id,
                            title=document["title"],
                            lang=document["locale"],
                            direction=document["direction"],
                            artifact_url=f"/api/sims/{sim_id}/download",
                            share_url=f"/sims/{sim_id}",
                            tier="A",
                            effective_model="verified/golden",
                            elapsed_ms=0,
                            check_count=document["receipt"]["check_count"],
                            heal_count=document["evidence"].get("heal_count", 0),
                        ),
                    ),
                )
        if verified_cache is None:
            return None
        entry = verified_cache.inspect(sim_id)
        if entry is None or entry.pinned:
            return None
        try:
            answer = (
                AnswerPayload.model_validate(entry.answer)
                if entry.answer is not None
                else None
            )
        except ValueError:
            return None
        return (
            entry.artifact,
            SharedSimulation(
                answer=answer,
                simulation=SimulationMetadata(
                    sim_id=entry.cache_id,
                    title=entry.title,
                    lang=entry.locale,
                    direction=entry.direction,
                    artifact_url=f"/api/sims/{entry.cache_id}/download",
                    share_url=f"/sims/{entry.cache_id}",
                    tier=entry.tier,
                    effective_model="verified/cache",
                    elapsed_ms=0,
                    check_count=entry.receipt.check_count,
                    heal_count=0,
                ),
            ),
        )

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        return index_response()

    @app.get("/sims/{sim_id}", response_class=HTMLResponse)
    async def shared_lesson(sim_id: str) -> HTMLResponse:
        if resolve_shareable(sim_id) is None:
            raise HTTPException(status_code=404, detail="shared simulation not found")
        return index_response()

    @app.post("/api/ask", response_model=AskAccepted, status_code=status.HTTP_202_ACCEPTED)
    async def ask(payload: AskRequest, request: Request) -> AskAccepted:
        question = unicodedata.normalize("NFKC", payload.question).strip()
        if not question:
            raise HTTPException(status_code=422, detail="question must not be blank")
        cached = (
            verified_cache.lookup_exact(question=question, locale=payload.locale)
            if verified_cache is not None
            else None
        )
        if cached is not None and cached.answer is not None:
            record = app.state.jobs.start_cached(cached)
        elif not app.state.jobs.has_capacity():
            record = app.state.jobs.start_capacity_fallback(payload.locale, "queue_full")
        else:
            client_ip = request.client.host if request.client else "unknown"
            limit_reason = app.state.generation_limiter.acquire(client_ip)
            record = (
                app.state.jobs.start_capacity_fallback(payload.locale, limit_reason)
                if limit_reason
                else app.state.jobs.start(question, payload.locale)
            )
        return AskAccepted(
            job_id=record.job_id,
            stream_url=f"/api/jobs/{record.job_id}/events",
            result_url=f"/api/jobs/{record.job_id}",
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
        if verified_cache is not None:
            for entry in verified_cache.list_live_entries():
                lessons.append(
                    {
                        "id": entry.cache_id,
                        "title": entry.title,
                        "domain": entry.domain,
                        "summary": entry.summary,
                        "instant": True,
                        "tier": entry.tier,
                    }
                )
        return {
            "contract_version": "1.0",
            "lessons": lessons,
        }

    @app.get("/api/gallery/{lesson_id}")
    async def gallery_lesson(lesson_id: str) -> dict:
        document = load_pinned_golden(lesson_id)
        if document is not None:
            sim_id = document["cache_id"]
            app.state.jobs.artifacts[sim_id] = document["artifact"]
            return {
                "contract_version": "1.0",
                "id": lesson_id,
                "answer": document["answer"],
                "simulation": {
                    "sim_id": sim_id,
                    "title": document["title"],
                    "lang": document["locale"],
                    "direction": document["direction"],
                    "artifact_url": f"/api/sims/{sim_id}/download",
                    "share_url": f"/sims/{sim_id}",
                    "tier": "A",
                    "effective_model": "verified/golden",
                    "elapsed_ms": 0,
                    "check_count": document["receipt"]["check_count"],
                    "heal_count": document["evidence"].get("heal_count", 0),
                },
            }
        resolved = resolve_shareable(lesson_id)
        if resolved is None or resolved[1].answer is None:
            raise HTTPException(status_code=404, detail="gallery lesson not found")
        shared = resolved[1]
        return {
            "contract_version": "1.0",
            "id": lesson_id,
            "answer": shared.answer.model_dump(mode="json"),
            "simulation": shared.simulation.model_dump(mode="json"),
        }

    @app.get("/api/sims/{sim_id}", response_model=SharedSimulation)
    async def shared_simulation(sim_id: str) -> SharedSimulation:
        resolved = resolve_shareable(sim_id)
        if resolved is None:
            raise HTTPException(status_code=404, detail="shared simulation not found")
        return resolved[1]

    @app.get("/api/sims/{sim_id}/download")
    async def download_sim(sim_id: str, inline: bool = Query(default=False)) -> Response:
        artifact = app.state.jobs.artifacts.get(sim_id)
        if artifact is None:
            resolved = resolve_shareable(sim_id)
            if resolved is None:
                raise HTTPException(status_code=404, detail="simulation not found")
            artifact = resolved[0]
        disposition = "inline" if inline else "attachment"
        return HTMLResponse(
            artifact,
            headers={
                "Cache-Control": CACHE_REVALIDATION,
                "Content-Disposition": f'{disposition}; filename="laysh-{sim_id}.html"',
                "Content-Security-Policy": PORTABLE_CSP,
                "X-Content-Type-Options": "nosniff",
            },
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
        }

    return app


app = create_app()
