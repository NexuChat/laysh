import re

from tests.conftest import wait_for_terminal
from tests.test_pipeline import ask


def test_index_versions_all_same_origin_static_assets(client):
    response = client.get("/")

    assert response.status_code == 200
    for asset in (
        "app.css",
        "locale.js",
        "translations.js",
        "app.js",
        "fonts/free-sans-arabic-latin.woff2",
        "fonts/free-serif-arabic-display.woff2",
    ):
        assert re.search(rf'/static/{re.escape(asset)}\?v=[^"&]+', response.text)


def test_static_assets_ignore_version_query_string(client):
    first = client.get("/static/app.js?v=first-deploy")
    second = client.get("/static/app.js?v=second-deploy")

    assert first.status_code == second.status_code == 200
    assert first.content == second.content


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


def test_parent_auto_sizes_only_the_matching_artifact_iframe(client):
    source = client.get("/static/app.js").text
    css = client.get("/static/app.css").text

    assert 'payload.type === "content-height"' in source
    assert "event.source !== frame.contentWindow" in source
    assert "Math.min(MAX_ARTIFACT_HEIGHT" in source
    assert 'frame.style.height = `${height}px`' in source
    assert "height: min(74vh, 760px)" not in css


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
    translations = client.get("/static/translations.js").text

    assert 'id="copy-share"' in html and "نسخ رابط الدرس" in html
    assert 'id="native-share"' in html and "مشاركة" in html
    assert 'id="share-status"' in html and 'aria-live="polite"' in html
    assert "تم نسخ الرابط" in translations and "Link copied" in translations
    assert "navigator.share" in source
    assert "navigator.clipboard.writeText" in source
    assert "/api/sims/${encodeURIComponent(simId)}" in source


def test_gallery_contract_is_available_offline(client):
    response = client.get("/api/gallery")
    assert response.status_code == 200
    assert response.json()["contract_version"] == "1.0"
    assert isinstance(response.json()["lessons"], list)


def test_gallery_includes_durable_verified_live_lesson_without_raw_question(
    tmp_path, monkeypatch, backend
):
    import json
    from copy import deepcopy

    from fastapi.testclient import TestClient

    from server.app import create_app
    from server.browser_verify import BrowserVerificationResult

    raw_question = "PRIVATE-GALLERY-CANARY explain a changing shadow"
    live_root = tmp_path / "cache" / "live"
    monkeypatch.setenv("LAYSH_CACHE_KEY_SECRET", "test-cache-secret")
    monkeypatch.setenv("LAYSH_LIVE_CACHE_ROOT", str(live_root))

    original_understand = backend.understand

    async def distinct_understanding(*args, **kwargs):
        understanding = deepcopy(await original_understand(*args, **kwargs))
        understanding["domain"] = "earth_science"
        understanding["canonical_intent"] = "shadow_motion"
        understanding["title"] = "حركة الظلال"
        understanding["tldr"] = "يتغير اتجاه الظل عندما يتغير اتجاه ضوء الشمس الظاهري."
        return understanding

    backend.understand = distinct_understanding
    with TestClient(
        create_app(
            backend=backend,
            job_timeout_seconds=2,
            browser_verifier=lambda _: BrowserVerificationResult.passing(),
        )
    ) as first_client:
        job_id = ask(first_client, raw_question)
        result = wait_for_terminal(first_client, job_id)
        live_id = result["simulation"]["sim_id"]

    with TestClient(
        create_app(
            backend=backend,
            job_timeout_seconds=2,
            browser_verifier=lambda _: BrowserVerificationResult.passing(),
        )
    ) as restarted_client:
        calls_before_replay = (
            backend.understand_calls,
            backend.generate_calls,
            backend.heal_calls,
            backend.qa_calls,
        )
        replay_job = ask(restarted_client, raw_question)
        replay_result = wait_for_terminal(restarted_client, replay_job)
        gallery_response = restarted_client.get("/api/gallery?locale=ar")
        lesson_response = restarted_client.get(f"/api/gallery/{live_id}")
        shared_response = restarted_client.get(f"/api/sims/{live_id}")
        share_page = restarted_client.get(f"/sims/{live_id}")

    gallery = gallery_response.json()
    public_surface = json.dumps(
        {
            "gallery": gallery,
            "lesson": lesson_response.json(),
            "shared": shared_response.json(),
            "share_page": share_page.text,
        },
        ensure_ascii=False,
    )
    live_lesson = next(lesson for lesson in gallery["lessons"] if lesson["id"] == live_id)

    assert [lesson["tier"] for lesson in gallery["lessons"][:6]] == ["A"] * 6
    assert live_lesson == {
        "id": live_id,
        "title": "حركة الظلال",
        "domain": "earth_science",
        "summary": "يتغير اتجاه الظل عندما يتغير اتجاه ضوء الشمس الظاهري.",
        "instant": True,
        "tier": "A",
        "missed_strictness_checks": [],
    }
    assert (
        lesson_response.status_code
        == shared_response.status_code
        == share_page.status_code
        == 200
    )
    assert lesson_response.json()["answer"] == result["answer"]
    assert lesson_response.json()["simulation"]["share_url"] == f"/sims/{live_id}"
    assert replay_result["status"] == "complete"
    assert replay_result["simulation"]["sim_id"] == live_id
    assert (
        backend.understand_calls,
        backend.generate_calls,
        backend.heal_calls,
        backend.qa_calls,
    ) == calls_before_replay
    assert raw_question not in public_surface
    assert "PRIVATE-GALLERY-CANARY" not in next(live_root.glob("*.json")).read_text(
        encoding="utf-8"
    )


def test_experimental_lesson_is_in_gallery_and_share_with_honest_receipt(
    tmp_path, monkeypatch, backend
):
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from server.app import create_app
    from server.browser_verify import BrowserVerificationResult

    live_root = tmp_path / "cache" / "live"
    monkeypatch.setenv("LAYSH_CACHE_KEY_SECRET", "test-cache-secret")
    monkeypatch.setenv("LAYSH_LIVE_CACHE_ROOT", str(live_root))
    passing = BrowserVerificationResult.passing()
    browser_result = replace(
        passing,
        passed=False,
        failures=[
            {
                "gate": "mobile_overlay_safe_band",
                "code": "mobile_overlay_count_exceeded",
                "expected": {"overlay_count_max": 1},
                "actual": {"overlay_count": 2},
            }
        ],
    )
    with TestClient(
        create_app(
            backend=backend,
            job_timeout_seconds=2,
            browser_verifier=lambda _: browser_result,
        )
    ) as test_client:
        job_id = ask(test_client, "success experimental gallery", "en")
        result = wait_for_terminal(test_client, job_id)
        sim_id = result["simulation"]["sim_id"]
        gallery = test_client.get("/api/gallery?locale=en").json()["lessons"]
        detail = test_client.get(f"/api/gallery/{sim_id}")
        shared = test_client.get(f"/api/sims/{sim_id}")
        share_page = test_client.get(f"/sims/{sim_id}")

    lesson = next(item for item in gallery if item["id"] == sim_id)
    expected_misses = ["mobile_overlay_safe_band.mobile_overlay_count_exceeded"]
    assert result["simulation"]["tier"] == "B"
    assert result["simulation"]["missed_strictness_checks"] == expected_misses
    assert lesson["tier"] == "B"
    assert lesson["missed_strictness_checks"] == expected_misses
    assert detail.status_code == shared.status_code == share_page.status_code == 200
    assert detail.json()["simulation"]["tier"] == "B"
    assert detail.json()["simulation"]["missed_strictness_checks"] == expected_misses
    assert shared.json()["simulation"]["missed_strictness_checks"] == expected_misses


def test_codex_backend_is_selected_only_by_explicit_configuration(monkeypatch, tmp_path):
    from server.app import create_app
    from server.codex_backend import CodexBackend

    monkeypatch.setenv("LAYSH_CODEX_BACKEND", "codex")
    monkeypatch.setenv("LAYSH_CACHE_KEY_SECRET", "test-only-cache-key")
    monkeypatch.setenv("LAYSH_LIVE_CACHE_ROOT", str(tmp_path / "live"))
    configured = create_app()
    assert isinstance(configured.state.jobs.backend, CodexBackend)
    assert configured.state.jobs.backend.settings.understand_model == "gpt-5.6-luna"
    assert configured.state.jobs.backend.settings.generate_model == "gpt-5.6-sol"
    assert configured.state.jobs.backend.executor.record_runtime is False
