"""Loads and validates Jarvis's settings from a single TOML file.

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
"""

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path("config.toml")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class BackendSettings:
    model: str = "gemma4:12b-it-qat"
    endpoint: str = "http://localhost:11434"
    num_ctx: int = 65536


@dataclass(frozen=True)
class HotkeySettings:
    screenshot_full: str = "ctrl+alt+s"
    screenshot_region: str = "ctrl+alt+r"
    shutdown: str = "ctrl+alt+q"


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


@dataclass(frozen=True)
class Settings:
    backend: BackendSettings = field(default_factory=BackendSettings)
    hotkeys: HotkeySettings = field(default_factory=HotkeySettings)
    vad: VadSettings = field(default_factory=VadSettings)
    tts: TtsSettings = field(default_factory=TtsSettings)
    capture: CaptureSettings = field(default_factory=CaptureSettings)
    sound_cues: SoundCueSettings = field(default_factory=SoundCueSettings)


_SECTIONS: dict[str, type] = {
    "backend": BackendSettings,
    "hotkeys": HotkeySettings,
    "vad": VadSettings,
    "tts": TtsSettings,
    "capture": CaptureSettings,
    "sound_cues": SoundCueSettings,
}


def _matches_type(value: Any, expected_type: type) -> bool:
    if isinstance(value, bool):
        return expected_type is bool
    if expected_type is float:
        return isinstance(value, (int, float))
    return isinstance(value, expected_type)


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
                f"[{section_name}].{name} must be {expected_type.__name__}, "
                f"got {type(value).__name__}: {value!r}"
            )
        kwargs[name] = value
    return cls(**kwargs)


def load_settings(path: str | Path = DEFAULT_CONFIG_PATH) -> Settings:
    path = Path(path)
    if not path.exists():
        return Settings()

    try:
        with path.open("rb") as config_file:
            raw = tomllib.load(config_file)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Malformed TOML in {path}: {exc}") from exc

    unknown_sections = set(raw) - set(_SECTIONS)
    if unknown_sections:
        raise ConfigError(
            f"Unknown section(s) in {path}: {', '.join(sorted(unknown_sections))}"
        )

    kwargs = {
        name: _build_section(name, cls, raw.get(name, {}))
        for name, cls in _SECTIONS.items()
    }
    return Settings(**kwargs)
