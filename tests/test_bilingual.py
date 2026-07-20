from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).parents[1]
ARABIC = re.compile(r"[\u0600-\u06ff]")


class _TranslatableTextParser(HTMLParser):
    _void = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, dict[str, str | None]]] = []
        self.untranslated: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in self._void:
            self.stack.append((tag, dict(attrs)))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if not value or not re.search(r"[A-Za-z\u0600-\u06ff]", value):
            return
        if any(tag in {"script", "style", "bdi"} for tag, _attrs in self.stack):
            return
        if any("data-i18n" in attrs for _tag, attrs in self.stack):
            return
        if any(
            {"brand", "brand-inline"} & set((attrs.get("class") or "").split())
            for _tag, attrs in self.stack
        ):
            return
        self.untranslated.append(value)


def _translations() -> dict[str, dict[str, str]]:
    source = (ROOT / "web" / "translations.js").read_text(encoding="utf-8")
    prefix = "window.LayshTranslations = "
    assert source.startswith(prefix) and source.rstrip().endswith(";")
    return json.loads(source[len(prefix) :].rstrip()[:-1])


def test_every_declared_ui_string_has_nonempty_arabic_and_english_copy():
    translations = _translations()

    assert set(translations) == {"ar", "en"}
    assert set(translations["ar"]) == set(translations["en"])
    assert all(value.strip() for catalog in translations.values() for value in catalog.values())

    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    declared = set(re.findall(r'data-i18n(?:-[a-z-]+)?="([a-z0-9_.-]+)"', html))
    dynamic = set(re.findall(r'\bt\("([a-z0-9_.-]+)"', script))

    assert declared
    assert declared | dynamic <= set(translations["ar"])
    assert ARABIC.search(" ".join(translations["ar"].values()))
    assert not ARABIC.search(" ".join(translations["en"].values()))

    parser = _TranslatableTextParser()
    parser.feed(html)
    assert parser.untranslated == []


def test_locale_bootstrap_detects_persists_and_applies_direction_before_app_init():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    bootstrap = (ROOT / "web" / "locale.js").read_text(encoding="utf-8")

    assert '/static/locale.js' in html
    assert html.index('/static/locale.js') < html.index('/static/app.css')
    assert "laysh.locale" in bootstrap
    assert "localStorage.getItem" in bootstrap
    assert "navigator.languages" in bootstrap
    assert "startsWith(\"ar\")" in bootstrap
    assert 'setAttribute("lang"' in bootstrap
    assert 'setAttribute("dir"' in bootstrap


def test_header_exposes_an_accessible_ar_en_switch_on_every_view(client):
    html = client.get("/").text

    assert 'id="locale-switch"' in html
    assert 'id="locale-ar"' in html and 'id="locale-en"' in html
    assert 'data-locale="ar"' in html and 'data-locale="en"' in html
    assert 'aria-pressed="true"' in html and 'aria-pressed="false"' in html
    assert "AR" in html and "EN" in html


def test_gallery_and_share_contracts_resolve_exact_language_variants(client):
    arabic = client.get("/api/gallery?locale=ar").json()["lessons"]
    english = client.get("/api/gallery?locale=en").json()["lessons"]

    assert len(arabic) == len(english) == 6
    assert {lesson["id"] for lesson in arabic} == {
        "buoyancy",
        "day_night",
        "moon_phases",
        "pendulum",
        "simple_circuit",
        "sound_pitch",
    }
    assert {lesson["id"] for lesson in english} == {
        "buoyancy_en",
        "day_night_en",
        "moon_phases_en",
        "pendulum_en",
        "simple_circuit_en",
        "sound_pitch_en",
    }

    for lesson in arabic + english:
        detail = client.get(f"/api/gallery/{lesson['id']}").json()
        expected_locale = "en" if lesson["id"].endswith("_en") else "ar"
        expected_dir = "ltr" if expected_locale == "en" else "rtl"
        assert detail["simulation"]["lang"] == expected_locale
        assert detail["simulation"]["direction"] == expected_dir
        share_url = detail["simulation"]["share_url"]
        shared = client.get(f"/api/sims/{detail['simulation']['sim_id']}").json()
        assert share_url == f"/sims/{detail['simulation']['sim_id']}"
        assert shared["simulation"]["lang"] == expected_locale
        assert shared["simulation"]["direction"] == expected_dir


def test_six_english_goldens_are_ltr_verified_qa_checked_and_language_clean():
    from server.goldens import list_pinned_goldens

    english = [document for document in list_pinned_goldens() if document["locale"] == "en"]

    assert len(english) == 6
    for document in english:
        assert document["golden_id"].endswith("_en")
        assert document["direction"] == "ltr"
        assert document["receipt"]["deterministic_passed"] is True
        assert document["receipt"]["browser_passed"] is True
        assert document["receipt"]["failed_gate_count"] == 0
        assert document["evidence"]["attempt"] >= 1
        assert document["evidence"]["heal_count"] >= 0
        assert document["evidence"]["qa"]["approved"] is True
        browser = document["evidence"]["browser"]
        assert browser["idleMotionSubjectChangedPixelRatio"] >= 0.01
        assert browser["renderOutputSweep"]["passed"] is True
        assert abs(browser["renderOutputSweep"]["rankCorrelation"]) >= 0.65
        marker = "<script>window.__LAYSH_LESSON__ = "
        start = document["artifact"].index(marker) + len(marker)
        end = document["artifact"].index(";</script>", start)
        lesson = json.loads(document["artifact"][start:end])
        visible_copy = " ".join(
            str(lesson.get(field) or "")
            for field in (
                "title",
                "tldr",
                "learning_objective",
                "misconception",
                "explanation_prompt",
                "transfer_prompt",
            )
        )
        assert lesson["lang"] == "en"
        assert not ARABIC.search(visible_copy)


def test_manifest_tracks_both_immutable_artifacts_for_each_lesson():
    manifest = json.loads(
        (ROOT / "out" / "cache" / "golden" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert len(manifest["lessons"]) == 12
    by_id = {lesson["id"]: lesson for lesson in manifest["lessons"]}
    for base in (
        "buoyancy",
        "day_night",
        "moon_phases",
        "pendulum",
        "simple_circuit",
        "sound_pitch",
    ):
        assert by_id[base]["locale"] == "ar"
        assert by_id[f"{base}_en"]["locale"] == "en"
        assert by_id[base]["artifact_sha256"] != by_id[f"{base}_en"]["artifact_sha256"]
