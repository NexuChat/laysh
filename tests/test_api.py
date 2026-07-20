from tests.conftest import wait_for_terminal
from tests.test_pipeline import ask


def test_root_is_arabic_first_ask_build_result_application(client):
    response = client.get("/")
    assert response.status_code == 200
    assert '<html lang="ar" dir="rtl">' in response.text
    assert "اسأل ليش، والعب الجواب" in response.text
    assert 'id="ask-form"' in response.text
    controller = client.get("/static/app.js").text
    assert 'headers["Last-Event-ID"]' in controller
    assert "AbortController" in controller
    assert 'sandbox="allow-scripts"' in response.text
    assert "allow-same-origin" not in response.text
    assert "fake-percent" not in response.text


def test_html_and_static_assets_revalidate_after_each_deploy(client):
    for path in ("/", "/static/app.js", "/static/app.css"):
        response = client.get(path)

        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache, must-revalidate"


def test_parent_accepts_only_narrow_origin_checked_runtime_error_beacon(client):
    source = client.get("/static/app.js").text
    assert 'event.origin !== "null"' in source
    assert "event.source !== frame.contentWindow" in source
    assert 'payload.source !== "laysh-artifact"' in source
    assert 'payload.code === "SIM_RUNTIME_ERROR"' in source


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
    assert inline.headers["cache-control"] == "no-cache, must-revalidate"
    assert download.headers["cache-control"] == "no-cache, must-revalidate"
    assert inline.text == download.text
    assert download.text.startswith("<!doctype html>")


def test_share_route_resolves_a_verified_golden_and_rejects_non_shareable_ids(client):
    known_id = "golden_moon_phases"

    page = client.get(f"/sims/{known_id}")
    shared = client.get(f"/api/sims/{known_id}")
    cold_download = client.get(f"/api/sims/{known_id}/download?inline=1")

    assert page.status_code == shared.status_code == cold_download.status_code == 200
    assert 'id="result-view"' in page.text
    assert shared.json()["status"] == "complete"
    assert shared.json()["simulation"]["sim_id"] == known_id
    assert shared.json()["simulation"]["share_url"] == f"/sims/{known_id}"
    assert shared.json()["simulation"]["artifact_url"] == (
        f"/api/sims/{known_id}/download"
    )
    assert cold_download.text.startswith("<!doctype html>")

    client.app.state.jobs.artifacts["sim_unverified"] = "<!doctype html><p>candidate</p>"
    assert client.get("/sims/not_known").status_code == 404
    assert client.get("/sims/sim_unverified").status_code == 404
    assert client.get("/api/sims/sim_unverified").status_code == 404


def test_result_view_has_arabic_copy_and_native_share_affordances(client):
    html = client.get("/").text
    source = client.get("/static/app.js").text

    assert 'id="copy-share"' in html and "نسخ رابط الدرس" in html
    assert 'id="native-share"' in html and "مشاركة" in html
    assert 'id="share-status"' in html and 'aria-live="polite"' in html
    assert "تم نسخ الرابط" in source
    assert "navigator.share" in source
    assert "navigator.clipboard.writeText" in source
    assert "/api/sims/${encodeURIComponent(simId)}" in source


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
