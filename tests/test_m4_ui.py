import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_arabic_ask_view_has_truthful_gallery_and_thumb_reachable_action(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    assert '<html lang="ar" dir="rtl">' in html
    assert 'id="question"' in html and 'dir="auto"' in html
    assert 'id="safe-example"' in html
    assert 'id="ask-submit"' in html
    assert 'class="gallery-card"' in html
    assert len(re.findall(r'class="gallery-card"', html)) == 6
    assert html.count("قريبًا بعد المراجعة") == 6
    assert "فوري" not in html
    assert "data-pinned=\"true\"" not in html


def test_local_font_is_preloaded_served_and_license_checked(client):
    html = client.get("/").text
    css = client.get("/static/app.css")
    font = client.get("/static/fonts/free-sans-arabic-latin.woff2")
    license_response = client.get("/static/fonts/FREEFONT-LICENSE.txt")

    assert 'rel="preload"' in html
    assert '/static/fonts/free-sans-arabic-latin.woff2' in html
    assert css.status_code == 200
    assert font.status_code == 200
    assert font.headers["content-type"] == "font/woff2"
    assert len(font.content) < 160_000
    assert license_response.status_code == 200
    assert "Special Font Exception" in license_response.text
    assert "font-display: swap" in css.text
    assert "letter-spacing: -" not in css.text
    assert "position: sticky" in css.text
    assert "@media (max-width: 390px)" in css.text
    assert "@media (prefers-reduced-motion: reduce)" in css.text


def test_build_controller_has_replay_watchdog_cancel_and_history_states(client):
    script = client.get("/static/app.js")
    assert script.status_code == 200
    source = script.text

    assert '"Last-Event-ID"' in source
    assert "AbortController" in source
    assert "pushState" in source and "popstate" in source
    assert "90_000" in source and "180_000" in source
    assert "heartbeat" in source
    assert "verification" in source
    assert "إعادة الاتصال" in source
    assert "ما زلنا نفحص" in source
    assert "في قائمة البناء" in source
    assert "إلغاء البناء" in source
    assert "Math.round" not in source


def test_result_and_every_designed_failure_have_arabic_recovery_copy(client):
    html = client.get("/").text
    source = client.get("/static/app.js").text

    assert 'sandbox="allow-scripts"' in html
    assert "allow-same-origin" not in html
    assert 'id="verification-receipt"' in html
    assert 'id="download"' in html
    assert 'id="retry-action"' in html
    assert 'id="gallery-action"' in html
    for reason in (
        "not_simulatable",
        "qa_inconclusive",
        "verification_exhausted",
        "simulation_runtime_error",
        "backend_unavailable",
        "cancelled",
        "unsafe_redirect",
    ):
        assert reason in source
    for arabic_copy in (
        "احتفظنا بالجواب",
        "جرّب البناء مرة أخرى",
        "تعذّر الاتصال بالخادم",
        "لا يمكننا متابعة هذا السؤال",
        "حدث خطأ داخل المحاكاة",
    ):
        assert arabic_copy in source


def test_m4_semantics_include_skip_link_status_and_text_alternative(client):
    html = client.get("/").text

    assert 'class="skip-link"' in html
    assert '<main id="main-content"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-describedby="question-help question-error"' in html
    assert 'id="simulation-alternative"' in html
    assert 'title="المحاكاة التفاعلية"' in html
    assert '<bdi id="effective-model" dir="ltr">' in html
