import ast
import inspect
from pathlib import Path

from jarvis.audio.tts import TtsOutput

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _project_imports(relative_path: str) -> set[str]:
    source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    return {name for name in imported if name.startswith("jarvis.")}


def test_common_tts_module_does_not_import_concrete_engines_or_factory():
    imports = _project_imports("src/jarvis/audio/tts.py")

    assert "jarvis.audio.tts_silero" not in imports
    assert "jarvis.audio.tts_piper" not in imports
    assert "jarvis.audio.tts_factory" not in imports


def test_factory_is_the_only_composition_layer_for_concrete_engines():
    factory_imports = _project_imports("src/jarvis/audio/tts_factory.py")

    assert "jarvis.audio.tts_silero" in factory_imports
    assert "jarvis.audio.tts_piper" in factory_imports


def test_tts_output_requires_an_explicit_engine_dependency():
    engine_parameter = inspect.signature(TtsOutput).parameters["engine"]

    assert engine_parameter.default is inspect.Parameter.empty
