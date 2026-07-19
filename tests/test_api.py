from tests.conftest import wait_for_terminal
from tests.test_pipeline import ask


def test_root_is_arabic_first_ask_build_result_application(client):
    response = client.get("/")
    assert response.status_code == 200
    assert '<html lang="ar" dir="rtl">' in response.text
    assert "اسأل ليش، والعب الجواب" in response.text
    assert 'id="ask-form"' in response.text
    assert "new EventSource" in response.text
    assert 'sandbox="allow-scripts"' in response.text
    assert "allow-same-origin" not in response.text
    assert "fake-percent" not in response.text


def test_parent_accepts_only_narrow_origin_checked_runtime_error_beacon(client):
    source = client.get("/").text
    assert 'event.origin !== "null"' in source
    assert "event.source !== simulationFrame.contentWindow" in source
    assert 'payload.source !== "laysh-artifact"' in source
    assert 'payload.code !== "SIM_RUNTIME_ERROR"' in source


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
    assert inline.text == download.text
    assert download.text.startswith("<!doctype html>")


def test_gallery_contract_is_available_offline(client):
    response = client.get("/api/gallery")
    assert response.status_code == 200
    assert response.json()["contract_version"] == "1.0"
    assert isinstance(response.json()["lessons"], list)
