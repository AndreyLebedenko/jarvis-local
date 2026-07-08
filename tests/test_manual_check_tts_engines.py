from argparse import Namespace
from pathlib import Path

from manual_check_tts_engines import PROMPTS, build_engine_paths, split_text_into_chunks


def test_prompt_catalog_covers_the_required_phrase_families():
    labels = [prompt.label for prompt in PROMPTS]
    languages = [prompt.language for prompt in PROMPTS]

    assert labels == [
        "russian",
        "english",
        "mixed_latin",
        "numbers",
        "short_answer",
        "code_like",
    ]
    assert languages == ["ru", "en", "ru", "ru", "ru", "en"]


def test_split_text_into_chunks_preserves_word_order_and_spacing():
    chunks = split_text_into_chunks("one two three four five", chunk_size=2)

    assert chunks == ("one two ", "three four ", "five")


def test_build_engine_paths_converts_present_arguments_to_paths():
    args = Namespace(
        piper_model=r"D:\\voices\\piper.onnx",
        piper_config=r"D:\\voices\\piper.onnx.json",
        kokoro_model=None,
        xtts_model_path=r"D:\\models\\xtts",
        xtts_config_path=None,
    )

    paths = build_engine_paths(args)

    assert paths.piper_model == Path(r"D:\\voices\\piper.onnx")
    assert paths.piper_config == Path(r"D:\\voices\\piper.onnx.json")
    assert paths.kokoro_model is None
    assert paths.xtts_model_path == Path(r"D:\\models\\xtts")
    assert paths.xtts_config_path is None
