from jarvis.app import (
    SYSTEM_PROMPT,
)

# --- system prompt -----------------------------------------------------


def test_system_prompt_includes_russian_and_short_answer_directives():
    assert "по-русски" in SYSTEM_PROMPT
    assert "коротко" in SYSTEM_PROMPT


def test_system_prompt_does_not_ask_for_language_markup():
    assert "<speak>" not in SYSTEM_PROMPT
    assert "<lang" not in SYSTEM_PROMPT
    assert "API names" in SYSTEM_PROMPT
    assert "identifiers" in SYSTEM_PROMPT
    assert "Markdown" in SYSTEM_PROMPT
    assert "языковую разметку добавлять не нужно" in SYSTEM_PROMPT
