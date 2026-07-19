import pytest


@pytest.mark.parametrize(
    ("question", "scenario"),
    [
        ("success", "success"),
        ("not simulatable", "non_simulatable"),
        ("unsafe canary", "unsafe"),
        ("broken first draft", "broken_first_draft"),
        ("exhausted heal", "exhausted_heal"),
        ("timeout", "timeout"),
    ],
)
def test_mock_backend_exposes_every_required_offline_fixture(backend, question, scenario):
    assert backend.scenario_for(question) == scenario
    assert scenario in backend.fixture_names


@pytest.mark.asyncio
async def test_non_simulatable_fixture_has_answer_and_no_generation_contract(backend):
    result = await backend.understand("not simulatable", "en")
    assert result["safe"] is True
    assert result["simulatable"] is False
    assert len(result["suggestions"]) == 3
    assert result["checks"] == []


@pytest.mark.asyncio
async def test_broken_first_draft_heals_to_the_hand_authored_module(backend):
    understanding = await backend.understand("broken first draft", "ar")
    broken = await backend.generate(understanding, "broken_first_draft")
    healed = await backend.heal(broken, understanding, ["forbidden capability"], 1)
    assert "fetch(" in broken["module_js"]
    assert "fetch(" not in healed["module_js"]
    assert backend.heal_calls == 1

