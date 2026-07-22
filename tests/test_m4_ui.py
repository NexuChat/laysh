import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_default_ask_view_has_truthful_gallery_and_thumb_reachable_action(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    assert '<html lang="en" dir="ltr">' in html
    assert 'id="question"' in html and 'dir="auto"' in html
    assert 'id="safe-example"' in html
    assert 'id="ask-submit"' in html
    assert 'class="gallery-card"' in html
    assert len(re.findall(r'class="gallery-card"', html)) == 6
    assert html.count("Coming after review") == 6
    assert "Instant" not in html
    assert "data-pinned=\"true\"" not in html


def test_kufi_font_is_preloaded_served_and_license_checked(client):
    html = client.get("/").text
    css = client.get("/static/app.css")
    arabic_font = client.get("/static/fonts/noto-kufi-ar.woff2")
    latin_font = client.get("/static/fonts/noto-kufi-latin.woff2")
    license_response = client.get("/static/fonts/OFL-1.1.txt")

    assert 'rel="preload"' in html
    assert '/static/fonts/noto-kufi-ar.woff2' in html
    assert '/static/fonts/noto-kufi-latin.woff2' in html
    assert css.status_code == 200
    for font in (arabic_font, latin_font):
        assert font.status_code == 200
        assert font.headers["content-type"] == "font/woff2"
        assert len(font.content) < 160_000
    assert license_response.status_code == 200
    assert "SIL OPEN FONT LICENSE Version 1.1" in license_response.text
    assert 'font-family: "Laysh Kufi"' in css.text
    assert "font-weight: 100 900" in css.text
    assert "font-display: swap" in css.text
    assert "letter-spacing: -" not in css.text
    assert "position: sticky" in css.text
    assert "@media (max-width: 390px)" in css.text
    assert "@media (prefers-reduced-motion: reduce)" in css.text


def test_result_kicker_has_dedicated_vertical_space_before_title(client):
    css = client.get("/static/app.css").text

    assert ".result-header .eyebrow" in css
    assert "margin-block-end: 1rem" in css
    assert "line-height: 1.8" in css
    assert ".result-header h1" in css
    assert "line-height: 1.2" in css


def test_build_controller_has_replay_watchdog_cancel_and_history_states(client):
    script = client.get("/static/app.js")
    translations = client.get("/static/translations.js")
    assert script.status_code == 200
    assert translations.status_code == 200
    source = script.text

    assert '"Last-Event-ID"' in source
    assert "AbortController" in source
    assert "pushState" in source and "popstate" in source
    assert "90_000" in source and "180_000" in source
    assert "heartbeat" in source
    assert "verification" in source
    for arabic_copy in ("إعادة الاتصال", "ما زلنا نفحص", "في قائمة البناء", "إلغاء البناء"):
        assert arabic_copy in translations.text
    assert "Math.round" not in source


def test_public_wait_copy_sets_an_honest_three_minute_expectation(client):
    html = client.get("/").text

    assert "قد يستغرق بناء تجربة جديدة حتى ٣ دقائق" in html


def test_result_and_every_designed_failure_have_arabic_recovery_copy(client):
    html = client.get("/").text
    source = client.get("/static/app.js").text
    translations = client.get("/static/translations.js").text

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
        assert arabic_copy in translations


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
