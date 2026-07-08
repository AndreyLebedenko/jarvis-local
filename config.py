"""Loads and validates Jarvis's settings, layered across two TOML files.

Documented in PROJECT.md's Architecture v1.0 section as the settings home:
model name, hotkeys, VAD/TTS parameters, loaded once at startup. Every
other module takes the resulting Settings object as a constructor
argument; none of them read files or environment variables directly.

Policy (see tasks/done/task-02-config.md):
- Missing config file -> built-in defaults, which mirror
  config.example.toml.
- Malformed TOML, or a value of the wrong type -> ConfigError.
- An unknown section, or an unknown key within a known section ->
  ConfigError. Typos are caught rather than silently ignored.
- A present section may omit keys; omitted keys fall back to their
  default value (partial overrides are allowed).

Config layering (story-v1.2.4-status-console-control-plane.md, task-2):
precedence, lowest to highest, is built-in defaults (each *Settings
dataclass's own field defaults) < config.toml (the human-edited file) <
config.ui.toml (written only by the Status Console - see
status_console.py's StatusConsoleApi). Both files are parsed and
validated through the exact same rules above - config.ui.toml is a
higher-precedence layer over the same schema, never a second, looser
source of truth, and precedence is per-key, not per-file: a key set in
config.toml but omitted from config.ui.toml still applies. Restart-to-
apply: load_settings() runs once at startup (main.py's run()/
run_with_status_console()); writing config.ui.toml while Jarvis is
already running has no live effect until the next start - there is no
file-watching or hot-reload here, by design (see PROJECT.md's Architecture
v1.2.4 section - "Do not implement live reconfiguration").
"""

import json
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, get_args, get_origin

DEFAULT_CONFIG_PATH = Path("config.toml")
DEFAULT_UI_CONFIG_PATH = Path("config.ui.toml")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class BackendSettings:
    model: str = "gemma4:12b-it-qat"
    endpoint: str = "http://localhost:11434"
    num_ctx: int = 65536
    read_timeout_seconds: float = 120.0
    # Optional Ollama tuning knobs for the spike. They default to None so the
    # current runtime contract stays unchanged unless a config file sets them.
    flash_attention: bool | None = None
    kv_cache_type: str | None = None


@dataclass(frozen=True)
class HotkeySettings:
    screenshot_full: str = "ctrl+alt+s"
    screenshot_region: str = "ctrl+alt+r"
    shutdown: str = "ctrl+alt+q"
    # mic_sleep_toggle added for task-09 (v1.1); registering the real
    # listener is task-10's job, per the v1.1 story's task split.
    mic_sleep_toggle: str = "ctrl+alt+m"
    # clipboard_submit added for task-10 (v1.1): task-08 built the reader
    # and event but deliberately left the real hotkey out of scope.
    clipboard_submit: str = "ctrl+alt+v"
    # thinking_toggle added for task-12 (thinking-mode story): toggles the
    # persistent runtime state consumed by future turns, see
    # thinking_mode.py. Real listener wired here; main.py wiring is
    # task-13's job.
    thinking_toggle: str = "ctrl+alt+t"


@dataclass(frozen=True)
class VadSettings:
    threshold: float = 0.5
    max_chunk_seconds: int = 30
    request_end_pause_seconds: float = 2.0


@dataclass(frozen=True)
class TtsSettings:
    voice: str = "baya"
    rate: float = 1.0


@dataclass(frozen=True)
class CaptureSettings:
    default_mode: str = "full"


@dataclass(frozen=True)
class SoundCueSettings:
    listening: str = "sounds/listening.wav"
    thinking: str = "sounds/thinking.wav"
    speaking: str = "sounds/speaking.wav"
    error: str = "sounds/error.wav"
    # clipboard/input_error/mic_sleep/mic_wake added for task-08/task-09
    # (v1.1); wired into the real SoundCuePlayer/ensure_generated() by
    # task-10.
    clipboard: str = "sounds/clipboard.wav"
    input_error: str = "sounds/input_error.wav"
    mic_sleep: str = "sounds/mic_sleep.wav"
    mic_wake: str = "sounds/mic_wake.wav"
    # thinking_on/thinking_off added for task-12 (thinking-mode story):
    # distinct from the existing "thinking" field above, which is the
    # per-turn processing cue, not this reasoning-mode on/off toggle.
    # Wiring into SoundCuePlayer/ensure_generated() is task-13's job.
    thinking_on: str = "sounds/thinking_on.wav"
    thinking_off: str = "sounds/thinking_off.wav"


@dataclass(frozen=True)
class ClipboardSettings:
    # 20000 chars (~5000 tokens at a rough 4 chars/token estimate) is a
    # conservative cap against an accidental huge paste (e.g. a log file)
    # blowing up local-context latency, while comfortably fitting a long
    # source file or document - see PROJECT.md.
    max_chars: int = 20000


@dataclass(frozen=True)
class MicrophoneSettings:
    # "" means "use sounddevice's default input device" (audio_in.py's
    # existing behavior before this field existed - see
    # stream_factory_for_device()). Any other value is matched against
    # sounddevice device names (see status_console.py's Status Console
    # microphone selector, story-v1.2.4-task-3-config-menu-iteration-1.md).
    device: str = ""


@dataclass(frozen=True)
class Settings:
    backend: BackendSettings = field(default_factory=BackendSettings)
    hotkeys: HotkeySettings = field(default_factory=HotkeySettings)
    vad: VadSettings = field(default_factory=VadSettings)
    tts: TtsSettings = field(default_factory=TtsSettings)
    capture: CaptureSettings = field(default_factory=CaptureSettings)
    sound_cues: SoundCueSettings = field(default_factory=SoundCueSettings)
    clipboard: ClipboardSettings = field(default_factory=ClipboardSettings)
    microphone: MicrophoneSettings = field(default_factory=MicrophoneSettings)


_SECTIONS: dict[str, type] = {
    "backend": BackendSettings,
    "hotkeys": HotkeySettings,
    "vad": VadSettings,
    "tts": TtsSettings,
    "capture": CaptureSettings,
    "sound_cues": SoundCueSettings,
    "clipboard": ClipboardSettings,
    "microphone": MicrophoneSettings,
}


def _matches_type(value: Any, expected_type: type) -> bool:
    origin = get_origin(expected_type)
    if origin is not None:
        return any(_matches_type(value, nested_type) for nested_type in get_args(expected_type))
    if isinstance(value, bool):
        return expected_type is bool
    if expected_type is float:
        return isinstance(value, (int, float))
    return isinstance(value, expected_type)


def _describe_type(expected_type: type) -> str:
    if expected_type is type(None):
        return "None"
    origin = get_origin(expected_type)
    if origin is None:
        return expected_type.__name__
    return " | ".join(_describe_type(nested_type) for nested_type in get_args(expected_type))


def _build_section(section_name: str, cls: type, raw: dict[str, Any]) -> Any:
    known_fields = {f.name: f.type for f in fields(cls)}
    unknown_keys = set(raw) - set(known_fields)
    if unknown_keys:
        raise ConfigError(
            f"Unknown key(s) in [{section_name}]: {', '.join(sorted(unknown_keys))}"
        )

    defaults = cls()
    kwargs = {}
    for name, expected_type in known_fields.items():
        if name not in raw:
            kwargs[name] = getattr(defaults, name)
            continue
        value = raw[name]
        if not _matches_type(value, expected_type):
            raise ConfigError(
                f"[{section_name}].{name} must be {_describe_type(expected_type)}, "
                f"got {type(value).__name__}: {value!r}"
            )
        kwargs[name] = value
    return cls(**kwargs)


def _read_toml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as config_file:
            return tomllib.load(config_file)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Malformed TOML in {path}: {exc}") from exc


def _validate_raw_config(raw: dict[str, Any], source: Path) -> None:
    """Unknown-section/unknown-key checks, run independently against each
    file's own raw dict before the two are merged - so an unknown key is
    always attributed to the file that actually contains it, not to
    whichever file happened to be merged last."""
    unknown_sections = set(raw) - set(_SECTIONS)
    if unknown_sections:
        raise ConfigError(
            f"Unknown section(s) in {source}: {', '.join(sorted(unknown_sections))}"
        )
    for section_name, cls in _SECTIONS.items():
        known_fields = {f.name for f in fields(cls)}
        unknown_keys = set(raw.get(section_name, {})) - known_fields
        if unknown_keys:
            raise ConfigError(
                f"Unknown key(s) in [{section_name}] ({source}): "
                f"{', '.join(sorted(unknown_keys))}"
            )


def load_settings(
    path: str | Path = DEFAULT_CONFIG_PATH,
    ui_path: str | Path | None = None,
) -> Settings:
    """ui_path defaults to sitting next to `path` (same directory,
    `config.ui.toml`), not an independently cwd-relative constant -
    otherwise a caller loading a base config from some other directory
    (a test's tmp_path, or config.example.toml's real repo-root location)
    would silently pick up an unrelated config.ui.toml from the process's
    actual cwd instead of the one that actually belongs next to `path`.
    Pass ui_path explicitly to point at a specific file regardless of
    where `path` lives (e.g. to prove one truly does not exist)."""
    path = Path(path)
    if ui_path is None:
        ui_path = path.with_name(DEFAULT_UI_CONFIG_PATH.name)
    else:
        ui_path = Path(ui_path)

    base_raw = _read_toml_file(path)
    _validate_raw_config(base_raw, path)
    ui_raw = _read_toml_file(ui_path)
    _validate_raw_config(ui_raw, ui_path)

    kwargs = {
        name: _build_section(
            name, cls, {**base_raw.get(name, {}), **ui_raw.get(name, {})}
        )
        for name, cls in _SECTIONS.items()
    }
    return Settings(**kwargs)


def write_ui_config(path: str | Path, *, model: str, microphone_device: str) -> None:
    """Writes config.ui.toml (story-v1.2.4-task-3-config-menu-iteration-1.md:
    "Saving writes only the UI config layer"). Never opens config.toml -
    this is the only writer this project has for any config file, and it
    only ever targets the UI layer's own path, so it structurally cannot
    overwrite the human-edited file regardless of what path argument it is
    given.

    Always rewrites the whole file with exactly these two fields: iteration
    1 has nothing else to preserve (config.ui.toml has no other writer, and
    is documented as machine-owned, not hand-edited - see this module's
    docstring). json.dumps() produces a quoted, escaped TOML basic string
    for both values without needing a TOML-writing dependency (Python's
    stdlib tomllib is read-only)."""
    content = (
        "# Auto-generated by the Jarvis Status Console. Do not edit by\n"
        "# hand - saving from the config menu overwrites this file.\n"
        "[backend]\n"
        f"model = {json.dumps(model)}\n"
        "\n"
        "[microphone]\n"
        f"device = {json.dumps(microphone_device)}\n"
    )
    Path(path).write_text(content, encoding="utf-8")
