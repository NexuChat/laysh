from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.assemble import PORTABLE_CSP
from server.browser_verify import BrowserVerificationResult
from server.codex_backend import MockCodexBackend
from tests.conftest import wait_for_terminal


@dataclass
class MutableClock:
    now: float = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


def _create_client(share_root: Path, clock: MutableClock, retention_seconds: int = 3600):
    from server.app import create_app

    return TestClient(
        create_app(
            backend=MockCodexBackend(),
            job_timeout_seconds=2,
            browser_verifier=lambda _: BrowserVerificationResult.passing(),
            share_root=share_root,
            share_retention_seconds=retention_seconds,
            share_clock=clock,
        )
    )


def _completed_simulation(client: TestClient, question: str = "success") -> dict:
    accepted = client.post(
        "/api/ask",
        json={"question": question, "locale": "ar"},
    )
    assert accepted.status_code == 202
    result = wait_for_terminal(client, accepted.json()["job_id"])
    assert result["status"] == "complete"
    return result["simulation"]


def test_completed_artifact_gets_a_stable_privacy_safe_share_url(tmp_path):
    share_root = tmp_path / "shares"
    clock = MutableClock()
    learner_question = "success private learner wording 7391"

    with _create_client(share_root, clock) as client:
        simulation = _completed_simulation(client, learner_question)
        first = client.post(f"/api/sims/{simulation['sim_id']}/share")
        second = client.post(f"/api/sims/{simulation['sim_id']}/share")

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    share = first.json()
    assert share["contract_version"] == "1.0"
    assert share["share_id"].startswith("sh_")
    assert share["share_url"] == f"/s/{share['share_id']}"
    assert share["download_url"] == f"/api/shares/{share['share_id']}/download"
    assert share["retention_seconds"] == 3600
    assert learner_question not in json.dumps(share, ensure_ascii=False)
    persisted = "\n".join(
        path.read_text(encoding="utf-8") for path in share_root.glob("*.json")
    )
    assert learner_question not in persisted


def test_share_survives_application_restart_and_serves_only_the_portable_artifact(tmp_path):
    share_root = tmp_path / "shares"
    clock = MutableClock()

    with _create_client(share_root, clock) as first_process:
        simulation = _completed_simulation(first_process)
        created = first_process.post(f"/api/sims/{simulation['sim_id']}/share").json()
        original = first_process.get(simulation["artifact_url"]).text

    with _create_client(share_root, clock, retention_seconds=60) as restarted_process:
        metadata = restarted_process.get(f"/api/shares/{created['share_id']}")
        played = restarted_process.get(created["share_url"])
        downloaded = restarted_process.get(created["download_url"])

    assert metadata.status_code == 200
    assert metadata.json() == created
    assert played.status_code == downloaded.status_code == 200
    assert played.text == downloaded.text == original
    assert played.headers["content-security-policy"] == PORTABLE_CSP
    assert played.headers["content-disposition"].startswith("inline")
    assert downloaded.headers["content-disposition"].startswith("attachment")


def test_expired_missing_and_identifier_tampered_shares_fail_the_same_closed_way(tmp_path):
    share_root = tmp_path / "shares"
    clock = MutableClock()

    with _create_client(share_root, clock, retention_seconds=30) as client:
        simulation = _completed_simulation(client)
        created = client.post(f"/api/sims/{simulation['sim_id']}/share").json()
        share_id = created["share_id"]
        changed = share_id[:-1] + ("0" if share_id[-1] != "0" else "1")

        missing = client.get("/api/shares/sh_00000000000000000000000000000000")
        tampered = client.get(f"/api/shares/{changed}")
        traversal = client.get("/api/shares/%2e%2e%2fsecret")
        clock.now += 31
        expired = client.get(f"/api/shares/{share_id}")
        expired_play = client.get(f"/s/{share_id}", follow_redirects=False)
        invalid_play = client.get("/s/%2e%2e%2fsecret", follow_redirects=False)

    assert not (share_root / f"{share_id}.json").exists()
    for response in (missing, tampered, traversal, expired):
        assert response.status_code == 404
        if response.headers.get("content-type", "").startswith("application/json"):
            assert response.json() == {"detail": "share unavailable"}
    for response in (expired_play, invalid_play):
        assert response.status_code == 303
        assert response.headers["location"] == "/#gallery"
        assert response.headers["cache-control"] == "no-store"


def test_successful_share_responses_cannot_outlive_server_side_expiry(tmp_path):
    share_root = tmp_path / "shares"
    clock = MutableClock()

    with _create_client(share_root, clock, retention_seconds=30) as client:
        simulation = _completed_simulation(client)
        created = client.post(f"/api/sims/{simulation['sim_id']}/share")
        share = created.json()
        metadata = client.get(f"/api/shares/{share['share_id']}")
        played = client.get(share["share_url"])
        downloaded = client.get(share["download_url"])

    for response in (created, metadata, played, downloaded):
        assert response.headers["cache-control"] == "no-store"


def test_persisted_record_tampering_fails_closed_without_serving_modified_html(tmp_path):
    share_root = tmp_path / "shares"
    clock = MutableClock()

    with _create_client(share_root, clock) as first_process:
        simulation = _completed_simulation(first_process)
        created = first_process.post(f"/api/sims/{simulation['sim_id']}/share").json()

    record_path = share_root / f"{created['share_id']}.json"
    document = json.loads(record_path.read_text(encoding="utf-8"))
    document["payload"]["artifact"] = "<!doctype html><script>alert(1)</script>"
    record_path.write_text(json.dumps(document), encoding="utf-8")

    with _create_client(share_root, clock) as restarted_process:
        metadata = restarted_process.get(f"/api/shares/{created['share_id']}")
        played = restarted_process.get(created["share_url"], follow_redirects=False)

    assert metadata.status_code == 404
    assert played.status_code == 303
    assert played.headers["location"] == "/#gallery"
    assert "alert(1)" not in played.text


def test_share_storage_rejects_symlink_root(tmp_path):
    from server.share_store import ShareStore

    real_root = tmp_path / "real-shares"
    real_root.mkdir()
    symlink_root = tmp_path / "linked-shares"
    symlink_root.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        ShareStore(root=symlink_root).create(
            artifact="<!doctype html><title>verified</title>",
            title="Verified",
            lang="en",
            direction="ltr",
            tier="B",
        )


def test_expiry_cleanup_does_not_delete_a_racing_replacement(tmp_path, monkeypatch):
    from server.share_store import ShareStore

    clock = MutableClock()
    root = tmp_path / "shares"
    store = ShareStore(root=root, retention_seconds=1, clock=clock)
    shared = store.create(
        artifact="<!doctype html><title>verified</title>",
        title="Verified",
        lang="en",
        direction="ltr",
        tier="B",
    )
    target = root / f"{shared.share_id}.json"
    original_read_text = Path.read_text
    replaced = False

    def replace_after_read(path, *args, **kwargs):
        nonlocal replaced
        content = original_read_text(path, *args, **kwargs)
        if path == target and not replaced:
            replaced = True
            replacement = root / ".racing-replacement"
            replacement.write_text("replacement-owned-by-another-writer", encoding="utf-8")
            os.replace(replacement, target)
        return content

    clock.now += 2
    monkeypatch.setattr(Path, "read_text", replace_after_read)

    assert store.resolve(shared.share_id) is None
    assert target.exists()
    assert original_read_text(target, encoding="utf-8") == "replacement-owned-by-another-writer"


def test_only_registered_verified_simulations_are_share_eligible(tmp_path):
    with _create_client(tmp_path / "shares", MutableClock()) as client:
        missing = client.post("/api/sims/sim_0000000000000000/share")
        malformed = client.post("/api/sims/..%2Fprivate/share")

    assert missing.status_code == malformed.status_code == 404
    assert missing.json() == malformed.json() == {"detail": "simulation unavailable"}


def test_model_echoed_learner_question_never_becomes_share_persistence(tmp_path):
    from server.app import create_app
    from server.browser_verify import BrowserVerificationResult
    from server.codex_backend import MockCodexBackend

    learner_question = "private learner phrasing 829104 about orbital light"

    class EchoingBackend(MockCodexBackend):
        async def understand(self, question, locale, *, runtime_context=None):
            understanding = await super().understand(
                question,
                locale,
                runtime_context=runtime_context,
            )
            understanding["title"] = question
            return understanding

    share_root = tmp_path / "shares"
    with TestClient(
        create_app(
            backend=EchoingBackend(),
            job_timeout_seconds=2,
            browser_verifier=lambda _: BrowserVerificationResult.passing(),
            share_root=share_root,
        )
    ) as client:
        accepted = client.post(
            "/api/ask",
            json={"question": learner_question, "locale": "en"},
        )
        result = wait_for_terminal(client, accepted.json()["job_id"])
        assert result["status"] == "complete"
        refused = client.post(
            f'/api/sims/{result["simulation"]["sim_id"]}/share'
        )

    assert refused.status_code == 404
    persisted = "\n".join(
        path.read_text(encoding="utf-8") for path in share_root.glob("*.json")
    )
    assert learner_question not in persisted


def test_zero_echo_comparison_normalizes_html_case_and_whitespace():
    from server.privacy import contains_learner_question_echo

    question = "  Why   does  this orbit change?  "
    assert contains_learner_question_echo(
        "<h1>WHY&nbsp;DOES THIS ORBIT CHANGE?</h1>",
        question,
    ) is True
    assert contains_learner_question_echo("A derived scientific title", question) is False


def test_zero_echo_comparison_detects_a_question_split_by_html_markup():
    from server.privacy import contains_learner_question_echo

    question = "Why does this orbit change?"

    assert contains_learner_question_echo(
        "<h1>Why <em>does this orbit</em> change?</h1>",
        question,
    ) is True


def test_zero_echo_decodes_js_unicode_escapes_without_evaluating_source():
    from server.privacy import contains_learner_question_echo

    question = "Why does A&B <orbit> change?"
    json_safe_artifact = (
        r"\u003ch1\u003eWhy d\u003cem\u003eoes\u003c/em\u003e "
        r"A\u0026amp;B \u0026lt;or\u003cspan\u003ebit\u003c/span\u003e"
        r"\u0026gt; change?\u003c/h1\u003e"
    )

    assert contains_learner_question_echo(json_safe_artifact, question) is True
    assert contains_learner_question_echo(
        r"\u0057hy does A&B <orbit> change?",
        question,
    ) is True
    assert contains_learner_question_echo(
        r"\u{57}hy does A\x26B <orbit> change?",
        question,
    ) is True
    assert contains_learner_question_echo(
        r"\u0057hy does ${globalThis.privateValue} change?",
        question,
    ) is False
    assert contains_learner_question_echo(
        r"\\u0057hy does A&B <orbit> change?",
        question,
    ) is False


@pytest.mark.parametrize("line_terminator", ["\n", "\r\n", "\r", "\u2028", "\u2029"])
def test_zero_echo_decodes_js_line_continuations(line_terminator):
    from server.privacy import contains_learner_question_echo

    artifact = f'const title = "Why\\{line_terminator} does this orbit change?";'

    assert contains_learner_question_echo(
        artifact,
        "Why does this orbit change?",
    ) is True


@pytest.mark.parametrize(
    "artifact",
    [
        r'const title = "Why\ orbit?";',
        r'const title = "Why \orbit?";',
    ],
)
def test_zero_echo_decodes_js_identity_escapes(artifact):
    from server.privacy import contains_learner_question_echo

    assert contains_learner_question_echo(artifact, "Why orbit?") is True


@pytest.mark.parametrize("digit", ["١", "９", "०"])
def test_zero_echo_treats_non_ascii_decimal_digits_as_js_identity_escapes(digit):
    from server.privacy import contains_learner_question_echo

    assert contains_learner_question_echo(
        f'const title = "Why \\{digit} orbit?";',
        f"Why {digit} orbit?",
    ) is True


def test_zero_echo_preserves_invalid_and_literal_backslash_sequences():
    from server.privacy import contains_learner_question_echo

    question = "Why orbit?"
    assert contains_learner_question_echo(r'"Why \x orbit?"', question) is False
    assert contains_learner_question_echo(r'"Why \u orbit?"', question) is False
    assert contains_learner_question_echo(r'"Why \\ orbit?"', question) is False


def test_result_share_action_has_localized_keyboard_feedback_contract():
    root = Path(__file__).parents[1]
    html = (root / "web" / "index.html").read_text(encoding="utf-8")
    application = (root / "web" / "app.js").read_text(encoding="utf-8")
    translations = (root / "web" / "translations.js").read_text(encoding="utf-8")

    assert 'id="share-result"' in html
    assert 'id="share-status"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert "navigator.clipboard.writeText" in application
    assert '`/api/sims/${encodeURIComponent(simulation.sim_id)}/share`' in application
    for key in (
        "result.share",
        "result.sharePending",
        "result.shareSuccess",
        "result.shareFailure",
    ):
        assert translations.count(f'"{key}"') == 2
