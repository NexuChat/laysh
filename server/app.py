from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse, StreamingResponse

from server.assemble import PORTABLE_CSP
from server.codex_backend import MockCodexBackend
from server.jobs import TERMINAL_STATES, JobManager
from server.schemas import AskAccepted, AskRequest, PublicResult
from server.settings import Settings

ROOT = Path(__file__).parents[1]


def create_app(
    backend: MockCodexBackend | None = None,
    job_timeout_seconds: float | None = None,
) -> FastAPI:
    settings = Settings.from_env()
    selected_backend = backend or MockCodexBackend()
    timeout = settings.job_timeout_seconds if job_timeout_seconds is None else job_timeout_seconds
    app = FastAPI(title="Laysh", version="0.1.0")
    app.state.jobs = JobManager(selected_backend, timeout)

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
    async def gallery() -> dict:
        return {
            "contract_version": "1.0",
            "lessons": [
                {
                    "id": "mock_moon_phases",
                    "title": "لماذا يتغير شكل القمر؟",
                    "instant": True,
                    "tier": "B",
                }
            ],
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
            "backend": "mock",
            "queue": {
                "active": app.state.jobs.active_count,
                "known_jobs": len(app.state.jobs.records),
            },
        }

    return app


app = create_app()

