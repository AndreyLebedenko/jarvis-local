from config import BackendSettings
from main import SYSTEM_PROMPT
from manual_check_speech_markup_contract import (
    PROMPTS,
    SYSTEM_PROMPT_UNDER_TEST,
    build_payload,
    generation_options,
    observe_plain_text,
    segment_text,
)


def test_prompt_catalog_covers_required_markup_handoff_cases():
    labels = [prompt.label for prompt in PROMPTS]

    assert labels == [
        "russian_only",
        "english_only",
        "mixed_identifiers",
        "quotes_and_slashes",
        "punctuation_heavy",
        "long_nuanced_pressure",
    ]


def test_generation_options_report_all_backend_knobs():
    settings = BackendSettings(
        temperature=0.2,
        top_p=0.9,
        top_k=40,
        min_p=0.05,
        repeat_penalty=1.1,
        repeat_last_n=128,
        seed=7,
        num_predict=256,
        stop=["</speak>"],
        draft_num_predict=8,
    )

    options = generation_options(settings)

    assert options == {
        "num_ctx": 65536,
        "flash_attention": None,
        "kv_cache_type": None,
        "temperature": 0.2,
        "top_p": 0.9,
        "top_k": 40,
        "min_p": 0.05,
        "repeat_penalty": 1.1,
        "repeat_last_n": 128,
        "seed": 7,
        "num_predict": 256,
        "stop": ["</speak>"],
        "draft_num_predict": 8,
    }


def test_default_prompt_under_test_starts_as_runtime_system_prompt():
    assert SYSTEM_PROMPT_UNDER_TEST == SYSTEM_PROMPT


def test_build_payload_uses_prompt_under_test_and_thinking_disabled():
    settings = BackendSettings(temperature=0.0, top_p=0.8)

    payload = build_payload(settings, "Проверка.")

    assert payload["model"] == settings.model
    assert payload["stream"] is True
    assert payload["think"] is False
    assert payload["messages"] == [
        {"role": "system", "content": SYSTEM_PROMPT_UNDER_TEST},
        {"role": "user", "content": "Проверка."},
    ]
    assert payload["options"] == {
        "num_ctx": 65536,
        "temperature": 0.0,
        "top_p": 0.8,
    }


def test_observe_plain_text_accepts_plain_speakable_answer():
    observation = observe_plain_text("Используй APIClient.")

    assert observation.no_language_tags is True
    assert observation.no_markdown_fences is True
    assert observation.has_speakable_text is True


def test_observe_plain_text_flags_language_tags_and_markdown_fences():
    observation = observe_plain_text("<speak>```text```</speak>")

    assert observation.no_language_tags is False
    assert observation.no_markdown_fences is False


def test_segment_text_reports_charset_language_segments():
    segments = segment_text("Функция parse_user_id готова.")

    assert [(segment.language, segment.text) for segment in segments] == [
        ("ru", "Функция"),
        ("en", "parse_user_id"),
        ("ru", "готова."),
    ]
