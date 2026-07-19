from scripts.live_m5_smokes import SMOKES, first_substantive_is_answer


def test_unseen_smokes_are_not_golden_fixture_questions_and_cover_both_languages():
    from server.goldens import load_golden_fixtures

    golden_questions = {
        fixture["question"] for fixture in load_golden_fixtures().values()
    }

    assert {smoke["locale"] for smoke in SMOKES} == {"ar", "en"}
    assert all(smoke["question"] not in golden_questions for smoke in SMOKES)
    assert all(smoke["id"].startswith("unseen_") for smoke in SMOKES)


def test_answer_first_measurement_ignores_non_substantive_heartbeats():
    assert first_substantive_is_answer(["heartbeat", "heartbeat", "answer", "stage"])
    assert not first_substantive_is_answer(["heartbeat", "stage", "answer"])
