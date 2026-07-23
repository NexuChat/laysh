from tests.golden_cases import VALID_UNDERSTANDING


def test_understand_prompt_does_not_reject_causal_science_by_question_wording():
    from server.codex_backend import CodexBackend

    prompt = CodexBackend._render_prompt("understand.md", VALID_UNDERSTANDING)
    instructions = " ".join(prompt.split("INPUT_JSON:\n", 1)[0].split())

    assert (
        "Treat safe causal science as simulatable when one bounded numeric control can "
        "visibly change a scientific actor."
        in instructions
    )
    assert (
        "Do not mark a lesson non-simulatable merely because the question asks why or how"
        in instructions
    )
    assert (
        "Reserve non-simulatable for cases with no honest bounded quantitative control"
        in instructions
    )

