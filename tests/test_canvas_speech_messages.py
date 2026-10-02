from jarvis.dialog.canvas_speech import (
    GUIDANCE_SECTION_LABEL,
    compose_canvas_speech_messages,
)


def test_messages_are_a_system_prompt_then_the_canvas_as_the_only_user_message():
    messages = compose_canvas_speech_messages("profile prompt", None, "the canvas")

    assert messages == [
        {"role": "system", "content": "profile prompt"},
        {"role": "user", "content": "the canvas"},
    ]


def test_speech_contract_follows_the_profile_prompt_after_a_blank_line():
    messages = compose_canvas_speech_messages("profile prompt", "speak ru", "canvas")

    assert messages[0]["content"] == "profile prompt\n\nspeak ru"


def test_a_missing_profile_prompt_leaves_only_the_contract():
    messages = compose_canvas_speech_messages(None, "speak ru", "canvas")

    assert messages[0]["content"] == "speak ru"


def test_guidance_is_a_labeled_system_section_between_prompt_and_contract():
    messages = compose_canvas_speech_messages(
        "profile prompt", "speak ru", "canvas", guidance="focus on the risks"
    )

    assert messages[0]["content"] == (
        f"profile prompt\n\n{GUIDANCE_SECTION_LABEL}\nfocus on the risks\n\nspeak ru"
    )


def test_guidance_never_enters_the_canvas_message():
    messages = compose_canvas_speech_messages(
        "profile prompt", None, "canvas", guidance="focus on the risks"
    )

    assert messages[1] == {"role": "user", "content": "canvas"}


def test_blank_guidance_adds_no_section():
    messages = compose_canvas_speech_messages(
        "profile prompt", None, "canvas", guidance="  \n"
    )

    assert messages[0]["content"] == "profile prompt"
