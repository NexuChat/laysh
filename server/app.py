from __future__ import annotations

import json
import unicodedata
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from server.assemble import PORTABLE_CSP
from server.browser_verify import BrowserVerificationResult, verify_artifact_in_browser
from server.cache import VerifiedCache
from server.codex_backend import CodexBackend, MockCodexBackend
from server.codex_runtime import CodexExecutor
from server.goldens import GOLDEN_FIXTURE_IDS, GOLDEN_ROOT, list_pinned_goldens, load_pinned_golden
from server.jobs import TERMINAL_STATES, JobManager
from server.schemas import AskAccepted, AskRequest, PublicResult
from server.settings import Settings

ROOT = Path(__file__).parents[1]


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
    public_timeout = (
        settings.public_job_timeout_seconds if job_timeout_seconds is None else job_timeout_seconds
    )
    app = FastAPI(title="Laysh", version="0.1.0")
    app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
    verified_cache = (
        VerifiedCache(
            root=ROOT / "out" / "cache" / "live",
            golden_root=GOLDEN_ROOT,
            secret=settings.cache_key_secret.encode(),
            contract_version="1.0",
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
    )

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        content = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(
            content,
            headers={
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
        )

    @app.post("/api/ask", response_model=AskAccepted, status_code=status.HTTP_202_ACCEPTED)
    async def ask(request: AskRequest) -> AskAccepted:
        question = unicodedata.normalize("NFKC", request.question).strip()
        if not question:
            raise HTTPException(status_code=422, detail="question must not be blank")
        record = app.state.jobs.start(question, request.locale)
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
        return {
            "contract_version": "1.0",
            "lessons": lessons,
        }

    @app.get("/api/gallery/{golden_id}")
    async def gallery_lesson(golden_id: str) -> dict:
        document = load_pinned_golden(golden_id)
        if document is None:
            raise HTTPException(status_code=404, detail="golden lesson not found")
        sim_id = "golden_" + document["artifact_sha256"][:16]
        app.state.jobs.artifacts[sim_id] = document["artifact"]
        return {
            "contract_version": "1.0",
            "id": golden_id,
            "answer": document["answer"],
            "simulation": {
                "sim_id": sim_id,
                "title": document["title"],
                "lang": document["locale"],
                "direction": document["direction"],
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
        return HTMLResponse(
            artifact,
            headers={
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
