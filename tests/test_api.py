from pathlib import Path

from tests.conftest import wait_for_terminal
from tests.test_pipeline import ask

ROOT = Path(__file__).parents[1]


def test_root_is_english_default_ask_build_result_application(client):
    response = client.get("/")
    assert response.status_code == 200
    assert '<html lang="en" dir="ltr">' in response.text
    assert "Ask why, then play the answer" in response.text
    assert 'id="ask-form"' in response.text
    controller = client.get("/static/app.js").text
    assert 'headers["Last-Event-ID"]' in controller
    assert "AbortController" in controller
    assert 'sandbox="allow-scripts"' in response.text
    assert "allow-same-origin" not in response.text
    assert "fake-percent" not in response.text


def test_parent_accepts_only_narrow_origin_checked_runtime_error_beacon(client):
    source = client.get("/static/app.js").text
    assert 'event.origin !== "null"' in source
    assert "event.source !== frame.contentWindow" in source
    assert 'payload.source !== "laysh-artifact"' in source
    assert 'payload.code === "SIM_RUNTIME_ERROR"' in source


def test_embed_height_protocol_is_bounded_and_keeps_a_scroll_fallback(client):
    page = client.get("/").text
    parent = client.get("/static/app.js").text
    bridge = (ROOT / "sim_shell" / "embed_bridge.js").read_text(encoding="utf-8")

    assert 'scrolling="auto"' in page
    assert 'payload.type === "layout-height"' in parent
    assert "Number.isFinite(payload.height)" in parent
    assert "payload.height >= 100" in parent
    assert "payload.height <= 100_000" in parent
    assert 'type: "layout-height"' in bridge
    assert "new ResizeObserver(scheduleHeightReport)" in bridge


def test_ask_normalizes_and_validates_question(client):
    accepted = client.post("/api/ask", json={"question": "  success  ", "locale": "ar"})
    assert accepted.status_code == 202
    assert client.post("/api/ask", json={"question": "   ", "locale": "ar"}).status_code == 422
    assert client.post(
        "/api/ask",
        json={"question": "x" * 601, "locale": "en"},
    ).status_code == 422


def test_health_is_fast_and_never_calls_backend(client, backend):
    before = (backend.understand_calls, backend.generate_calls, backend.heal_calls)
    response = client.get("/healthz")
    after = (backend.understand_calls, backend.generate_calls, backend.heal_calls)
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "backend": "mock",
        "queue": {"active": 0, "known_jobs": 0},
    }
    assert after == before


def test_result_artifact_can_be_rendered_inline_or_downloaded(client):
    job_id = ask(client, "success")
    result = wait_for_terminal(client, job_id)
    url = result["simulation"]["artifact_url"]

    inline = client.get(f"{url}?inline=1")
    download = client.get(url)
    assert inline.headers["content-disposition"].startswith("inline")
    assert download.headers["content-disposition"].startswith("attachment")
    assert 'data-laysh-embed-bridge' in inline.text
    assert 'data-laysh-embed-bridge' not in download.text
    bridge_start = inline.text.index('<script data-laysh-embed-bridge')
    bridge_end = inline.text.index('</script></body>') + len('</script>')
    assert inline.text.replace(inline.text[bridge_start:bridge_end], "", 1) == download.text
    assert download.text.startswith("<!doctype html>")


def test_gallery_contract_is_available_offline(client):
    response = client.get("/api/gallery")
    assert response.status_code == 200
    assert response.json()["contract_version"] == "1.0"
    assert isinstance(response.json()["lessons"], list)


def test_codex_backend_is_selected_only_by_explicit_configuration(monkeypatch):
    from server.app import create_app
    from server.codex_backend import CodexBackend

    monkeypatch.setenv("LAYSH_CODEX_BACKEND", "codex")
    configured = create_app()
    assert isinstance(configured.state.jobs.backend, CodexBackend)
    assert configured.state.jobs.backend.settings.understand_model == "gpt-5.6-luna"
    assert configured.state.jobs.backend.settings.generate_model == "gpt-5.6-sol"
    assert configured.state.jobs.backend.executor.record_runtime is False
