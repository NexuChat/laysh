from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.golden_cases import VALID_MODULE_OUTPUT, VALID_UNDERSTANDING

ROOT = Path(__file__).parents[1]


def _translation_inventory() -> dict[str, dict[str, str]]:
    script = ROOT / "web" / "translations.js"
    completed = subprocess.run(
        [
            "node",
            "-e",
            (
                "const fs=require('node:fs');const vm=require('node:vm');"
                "const context={window:{}};vm.runInNewContext("
                "fs.readFileSync(process.argv[1],'utf8'),context);"
                "process.stdout.write(JSON.stringify(context.window.LayshTranslations));"
            ),
            str(script),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_locale_inventory_covers_both_languages_and_every_core_failure_surface():
    inventory = _translation_inventory()

    assert set(inventory) == {"ar", "en"}
    assert set(inventory["ar"]) == set(inventory["en"])
    assert all(value.strip() for catalog in inventory.values() for value in catalog.values())
    required = {
        "document.title",
        "nav.skip",
        "locale.control",
        "landing.title",
        "ask.label",
        "ask.submit",
        "gallery.title",
        "gallery.launch",
        "build.title",
        "build.cancel",
        "result.ready",
        "result.download",
        "receipt.summary",
        "receipt.model",
        "failure.retry",
        "failure.gallery",
    }
    for reason in (
        "not_simulatable",
        "qa_inconclusive",
        "verification_exhausted",
        "generation_failed",
        "simulation_runtime_error",
        "backend_unavailable",
        "cancelled",
        "timed_out",
        "unsafe_redirect",
    ):
        required.update(
            {
                f"failure.{reason}.eyebrow",
                f"failure.{reason}.title",
                f"failure.{reason}.copy",
            }
        )
    assert required <= set(inventory["ar"])


def test_application_loads_locale_assets_and_exposes_an_explicit_locale_control():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    source = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    locale_source = (ROOT / "web" / "locale.js").read_text(encoding="utf-8")

    assert html.index("/static/translations.js") < html.index("/static/locale.js")
    assert html.index("/static/locale.js") < html.index("/static/app.js")
    assert 'id="locale-control"' in html
    assert 'data-i18n="landing.title"' in html
    assert "LayshLocale.current()" in source
    assert "locale: currentLocale" in source
    assert "`/api/gallery?locale=${currentLocale}`" in source
    assert 'document.addEventListener("click"' not in locale_source
    assert 'byId("locale-control").addEventListener("click"' in locale_source
    assert 'source !== "locale-control"' in locale_source
    assert 'localStorage.setItem(STORAGE_KEY, locale)' in locale_source


def test_gallery_results_are_localized_before_they_are_served(client):
    from server.goldens import (
        PINNED_ENGLISH_LESSONS,
        _artifact_lesson_and_module,
        list_pinned_goldens,
    )

    for document in list_pinned_goldens():
        golden_id = document["golden_id"]
        response = client.get(f"/api/gallery/{golden_id}?locale=en")

        assert response.status_code == 200
        result = response.json()
        simulation = result["simulation"]
        assert simulation["lang"] == "en"
        assert simulation["direction"] == "ltr"
        assert simulation["title"] == PINNED_ENGLISH_LESSONS[golden_id]["title"]

        artifact = client.get(simulation["artifact_url"]).text
        lesson, _ = _artifact_lesson_and_module(artifact)
        assert '<html lang="en" dir="ltr">' in artifact
        assert lesson["lang"] == "en"
        assert lesson["title"] == simulation["title"]
        assert result["answer"]["tldr"] == lesson["tldr"]


def test_direction_contract_covers_application_and_existing_portable_shell():
    from server.assemble import assemble_artifact

    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert '<html lang="ar" dir="rtl">' in html
    assert 'id="answer-formula" dir="ltr"' in html
    assert 'id="effective-model" dir="ltr"' in html

    module_output = {
        **VALID_MODULE_OUTPUT,
        "module_js": (ROOT / "tests" / "fixtures" / "moon_phase_module.js").read_text(
            encoding="utf-8"
        ),
    }
    arabic = assemble_artifact(VALID_UNDERSTANDING, module_output)
    from server.codex_backend import _success_understanding

    english_understanding = _success_understanding("en")
    english = assemble_artifact(english_understanding, module_output)

    assert '<html lang="ar" dir="rtl">' in arabic
    assert '<html lang="en" dir="ltr">' in english
    assert '<p class="formula" id="formula" dir="ltr">' in arabic
    assert '<p class="formula" id="formula" dir="ltr">' in english
