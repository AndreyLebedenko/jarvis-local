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
run_with_status_console()); writing restart-bound settings to config.ui.toml
while Jarvis is already running has no live effect until the next start.
The v1.4 MCP module switch is the explicit exception: its Control Center
action first calls McpHost's live lifecycle API, then persists the confirmed
state by updating only [mcp].enabled in this same layered file for the next
start. There is still no file-watching or generic hot-reload (see PROJECT.md's
Architecture v1.2.4 section - "Do not implement live reconfiguration").
"""

import enum
import json
import re
import tomllib
from dataclasses import MISSING, dataclass, field, fields
from pathlib import Path
from typing import Any, get_args, get_origin

DEFAULT_CONFIG_PATH = Path("config.toml")
DEFAULT_UI_CONFIG_PATH = Path("config.ui.toml")
BUILTIN_TOOL_PROVIDER_NAME = "builtin"

_TOML_SECTION_LINE = re.compile(
    r"^[ \t]*\[[ \t]*(?P<name>[A-Za-z0-9_.-]+)[ \t]*\][ \t]*(?:#.*)?(?:\r?\n)?$"
)
_TOML_ENABLED_LINE = re.compile(r"^(?P<indent>[ \t]*)enabled[ \t]*=")


class ConfigError(Exception):
    pass


class DataBoundary(enum.Enum):
    """Furthest declared destination an MCP tool may send request data to.

    UNKNOWN is the honest default: absence of configuration must never be
    interpreted as proof that a provider stays on this machine.
    """

    LOCAL = "local"
    LAN = "lan"
    INTERNET = "internet"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class BackendSettings:
    model: str = "gemma4:12b-it-qat"
    endpoint: str = "http://localhost:11434"
    num_ctx: int = 65536
    read_timeout_seconds: float = 120.0
    # Optional Ollama tuning knobs. They default to None so the current runtime
    # contract stays unchanged unless a config file sets them.
    flash_attention: bool | None = None
    kv_cache_type: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    min_p: float | None = None
    repeat_penalty: float | None = None
    repeat_last_n: int | None = None
    seed: int | None = None
    num_predict: int | None = None
    stop: list[str] | None = None
    draft_num_predict: int | None = None


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
    resume_cooldown_seconds: float = 1.0


@dataclass(frozen=True)
class SileroTtsSettings:
    model: str = field(default="v3_1_ru", metadata={"non_empty": True})
    language: str = field(default="ru", metadata={"non_empty": True})
    speaker: str = field(default="baya", metadata={"non_empty": True})
    sample_rate: int = field(
        default=48000, metadata={"minimum": 0, "exclusive_minimum": True}
    )
    put_accent: bool | None = None
    put_yo: bool | None = None

    @property
    def engine(self) -> str:
        return "silero"


@dataclass(frozen=True)
class PiperTtsSettings:
    model: str = field(metadata={"non_empty": True})
    config_path: str | None = field(default=None, metadata={"non_empty": True})
    use_cuda: bool = False
    espeak_data_dir: str | None = field(default=None, metadata={"non_empty": True})
    download_dir: str | None = field(default=None, metadata={"non_empty": True})
    speaker_id: int | None = field(default=None, metadata={"minimum": 0})
    length_scale: float | None = field(
        default=None, metadata={"minimum": 0, "exclusive_minimum": True}
    )
    noise_scale: float | None = field(
        default=None, metadata={"minimum": 0, "exclusive_minimum": True}
    )
    noise_w_scale: float | None = field(
        default=None, metadata={"minimum": 0, "exclusive_minimum": True}
    )
    normalize_audio: bool = True
    volume: float = field(
        default=1.0, metadata={"minimum": 0, "exclusive_minimum": True}
    )

    @property
    def engine(self) -> str:
        return "piper"


TtsLanguageSettings = SileroTtsSettings | PiperTtsSettings
TtsFieldValue = str | int | float | bool | None


@dataclass(frozen=True)
class TtsFieldSpec:
    name: str
    kind: str
    nullable: bool
    required: bool
    default: TtsFieldValue
    non_empty: bool
    minimum: int | float | None
    exclusive_minimum: bool


TTS_ROUTE_TYPES: dict[str, type[SileroTtsSettings] | type[PiperTtsSettings]] = {
    "silero": SileroTtsSettings,
    "piper": PiperTtsSettings,
}


def tts_route_field_specs(engine: str) -> tuple[TtsFieldSpec, ...]:
    """Return the public projection of the typed TOML route contract."""
    try:
        route_type = TTS_ROUTE_TYPES[engine]
    except KeyError as exc:
        raise ValueError(f"Unsupported TTS engine: {engine!r}") from exc

    specs = []
    for route_field in fields(route_type):
        value_types = get_args(route_field.type)
        nullable = type(None) in value_types
        value_type = next(
            (candidate for candidate in value_types if candidate is not type(None)),
            route_field.type,
        )
        kinds = {str: "string", int: "integer", float: "number", bool: "boolean"}
        default = None if route_field.default is MISSING else route_field.default
        specs.append(
            TtsFieldSpec(
                name=route_field.name,
                kind=kinds[value_type],
                nullable=nullable,
                required=route_field.default is MISSING,
                default=default,
                non_empty=bool(route_field.metadata.get("non_empty", False)),
                minimum=route_field.metadata.get("minimum"),
                exclusive_minimum=bool(
                    route_field.metadata.get("exclusive_minimum", False)
                ),
            )
        )
    return tuple(specs)


def tts_field_matches_spec(value: object, spec: TtsFieldSpec) -> bool:
    """The one implementation of "does this raw value match this TTS
    field's type" - shared by config.py's own TOML route parsing and
    transport.py's transport-payload route parsing, so a future field
    kind cannot be handled correctly on one side and silently mishandled
    on the other."""
    if value is None:
        return spec.nullable
    return {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, int | float) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
    }[spec.kind]


_SPEC_KIND_TYPE_NAMES = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
}


def _describe_spec_kind(spec: TtsFieldSpec) -> str:
    """Renders a TtsFieldSpec.kind using the same Python type names
    _describe_type() would have produced for the underlying dataclass
    field - config.py's ConfigError wording must not change even though
    validation now goes through the shared, spec-based predicate."""
    name = _SPEC_KIND_TYPE_NAMES[spec.kind]
    return f"{name} | None" if spec.nullable else name


def tts_route_values(route: TtsLanguageSettings) -> dict[str, TtsFieldValue]:
    return {
        route_field.name: getattr(route, route_field.name)
        for route_field in fields(route)
    }


def _default_tts_languages() -> dict[str, TtsLanguageSettings]:
    return {"ru": SileroTtsSettings()}


@dataclass(frozen=True)
class TtsSettings:
    languages: dict[str, TtsLanguageSettings] = field(
        default_factory=_default_tts_languages
    )


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
class McpToolAdapterSettings:
    """Maps one provider tool onto Jarvis's stable public tool surface."""

    public_name: str
    description: str | None = None
    allowed_arguments: tuple[str, ...] | None = None
    fixed_arguments: dict[str, str | int | float | bool] = field(default_factory=dict)


@dataclass(frozen=True)
class McpServerSettings:
    """One configured MCP tool-provider component (VISION.md's component
    model sense): a stdio subprocess command plus its own enable flag, so
    a single server can be turned off without touching [mcp].enabled -
    the module-wide switch story-v1.4.0 task 3's registry/interception
    gate on."""

    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    data_boundary: DataBoundary = DataBoundary.UNKNOWN
    tool_boundaries: dict[str, DataBoundary] = field(default_factory=dict)
    tool_adapters: dict[str, McpToolAdapterSettings] = field(default_factory=dict)

    def boundary_for(self, tool_name: str) -> DataBoundary:
        return self.tool_boundaries.get(tool_name, self.data_boundary)


@dataclass(frozen=True)
class McpSettings:
    """Off by default per the two-tier locality contract (PROJECT.md):
    story-v1.4.0 task 3's McpHost is always constructed as the persistent
    controller, but with enabled=False it stays inert: no client object,
    server process, connection, or registry entry exists."""

    enabled: bool = False
    presentation_strategy: str = "native"
    max_tool_calls_per_turn: int = 3
    servers: dict[str, McpServerSettings] = field(default_factory=dict)


@dataclass(frozen=True)
class MicrophoneSettings:
    # "" means "use sounddevice's default input device" (audio_in.py's
    # existing behavior before this field existed - see
    # stream_factory_for_device()). Any other value is matched against
    # sounddevice device names (see status_console.py's Status Console
    # microphone selector, story-v1.2.4-task-3-config-menu-iteration-1.md).
    device: str = ""


@dataclass(frozen=True)
class JournalSettings:
    enabled: bool = True
    root: str = "journal"


DEFAULT_FORK_SEED_MAX_CHARS = 12000


@dataclass(frozen=True)
class MemorySettings:
    root: str = "memory"
    self_file: str = "self.md"
    memory_file: str = "memory.md"
    self_max_chars: int = field(
        default=8000, metadata={"minimum": 0, "exclusive_minimum": True}
    )
    memory_max_chars: int = field(
        default=8000, metadata={"minimum": 0, "exclusive_minimum": True}
    )
    fork_seed_max_chars: int = field(
        default=DEFAULT_FORK_SEED_MAX_CHARS,
        metadata={"minimum": 0, "exclusive_minimum": True},
    )


# Dialog-prompt defaults (task-v1.2.12-external-prompt-config.md). These are
# runtime dialog data sent to the model, not UI text - deliberately not part
# of ui_text.py's UI catalog and not governed by [ui].language. Russian
# typography is canonical here (see the agent instructions' exception for
# runtime user-facing strings).
_DEFAULT_SYSTEM_PROMPT = (
    "Ты - Джарвис, локальный голосовой ассистент пользователя. Отвечай "
    "по-русски, если пользователь явно не попросил другой язык. Отвечай "
    "коротко и по существу: одно-два предложения, если не попросили "
    "подробностей - чем длиннее ответ, тем дольше пользователь ждёт, пока "
    "он прозвучит. Не используй Markdown, если пользователь явно не просит "
    "форматирование. Английские термины, API names, identifiers, короткие "
    "английские фразы и цитаты можно писать обычным текстом там, где они "
    "уместны; языковую разметку добавлять не нужно. Если вместе с голосовым "
    "сообщением пришёл скриншот экрана пользователя, отвечай с учётом того, "
    "что на нём видно."
)
_DEFAULT_WARMUP_PROMPT = "Привет"


@dataclass(frozen=True)
class PromptSettings:
    """The dialog prompts sent to the model: `system` opens every turn's
    message list, `warmup` is the throwaway request main.warm_up() sends
    before user input is accepted."""

    system: str = _DEFAULT_SYSTEM_PROMPT
    warmup: str = _DEFAULT_WARMUP_PROMPT


@dataclass(frozen=True)
class UiSettings:
    """UI chrome language only (story-v1.2.11-ui-english-localization.md):
    the dialog language - system prompt, TTS output, speech markup - is
    runtime data and is not governed by this setting.

    The default and the supported set are literals here, not imports from
    ui_text.py: config.py must stay free of project-module imports (see
    test_config_has_no_project_import_dependencies). A test asserts the
    two modules agree."""

    language: str = "en"


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
    ui: UiSettings = field(default_factory=UiSettings)
    prompts: PromptSettings = field(default_factory=PromptSettings)
    mcp: McpSettings = field(default_factory=McpSettings)
    journal: JournalSettings = field(default_factory=JournalSettings)
    memory: MemorySettings = field(default_factory=MemorySettings)


_SECTIONS: dict[str, type] = {
    "backend": BackendSettings,
    "hotkeys": HotkeySettings,
    "vad": VadSettings,
    "tts": TtsSettings,
    "capture": CaptureSettings,
    "sound_cues": SoundCueSettings,
    "clipboard": ClipboardSettings,
    "microphone": MicrophoneSettings,
    "ui": UiSettings,
    "prompts": PromptSettings,
    "mcp": McpSettings,
    "journal": JournalSettings,
    "memory": MemorySettings,
}

SUPPORTED_UI_LANGUAGES = ("en", "ru")
SUPPORTED_TTS_LANGUAGES = frozenset({"ru", "en"})
SUPPORTED_TTS_ENGINES = frozenset(TTS_ROUTE_TYPES)


def _matches_type(value: Any, expected_type: type) -> bool:
    origin = get_origin(expected_type)
    if origin is not None:
        if origin is list:
            (item_type,) = get_args(expected_type)
            return isinstance(value, list) and all(
                _matches_type(item, item_type) for item in value
            )
        return any(
            _matches_type(value, nested_type) for nested_type in get_args(expected_type)
        )
    if isinstance(value, bool):
        return expected_type is bool
    if expected_type is float:
        return isinstance(value, int | float)
    return isinstance(value, expected_type)


def _describe_type(expected_type: type) -> str:
    if expected_type is type(None):
        return "None"
    origin = get_origin(expected_type)
    if origin is None:
        return expected_type.__name__
    return " | ".join(
        _describe_type(nested_type) for nested_type in get_args(expected_type)
    )


def _build_section(section_name: str, cls: type, raw: dict[str, Any]) -> Any:
    if cls is TtsSettings:
        return _build_tts_section(section_name, raw)
    if cls is UiSettings:
        return _build_ui_section(section_name, raw)
    if cls is PromptSettings:
        return _build_prompts_section(section_name, raw)
    if cls is McpSettings:
        return _build_mcp_section(section_name, raw)
    if cls is MemorySettings:
        return _build_memory_section(section_name, raw)
    return _build_plain_section(section_name, cls, raw)


def _build_plain_section(section_name: str, cls: type, raw: dict[str, Any]) -> Any:
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
        if not _matches_type(value, expected_type):  # type: ignore[arg-type]
            description = _describe_type(expected_type)  # type: ignore[arg-type]
            raise ConfigError(
                f"[{section_name}].{name} must be {description}, "
                f"got {type(value).__name__}: {value!r}"
            )
        kwargs[name] = value
    return cls(**kwargs)


def _build_ui_section(section_name: str, raw: dict[str, Any]) -> "UiSettings":
    settings = _build_plain_section(section_name, UiSettings, raw)
    if settings.language not in SUPPORTED_UI_LANGUAGES:
        supported = ", ".join(SUPPORTED_UI_LANGUAGES)
        raise ConfigError(
            f"[{section_name}].language must be one of: {supported}; "
            f"got {settings.language!r}"
        )
    return settings


def _build_prompts_section(section_name: str, raw: dict[str, Any]) -> "PromptSettings":
    settings = _build_plain_section(section_name, PromptSettings, raw)
    for name in ("system", "warmup"):
        if not getattr(settings, name).strip():
            raise ConfigError(
                f"[{section_name}].{name} must be a non-empty string; an empty "
                "prompt is almost certainly a config mistake"
            )
    return settings


def _build_memory_section(section_name: str, raw: dict[str, Any]) -> "MemorySettings":
    settings = _build_plain_section(section_name, MemorySettings, raw)
    for name in ("self_max_chars", "memory_max_chars", "fork_seed_max_chars"):
        value = getattr(settings, name)
        if value <= 0:
            raise ConfigError(
                f"[{section_name}].{name} must be a positive int, got {value!r}"
            )
    for name in ("root", "self_file", "memory_file"):
        value = getattr(settings, name)
        if not value.strip():
            raise ConfigError(f"[{section_name}].{name} must be a non-empty string")
        if Path(value).is_absolute() and name != "root":
            raise ConfigError(f"[{section_name}].{name} must be relative")
        if ".." in Path(value).parts and name != "root":
            raise ConfigError(f"[{section_name}].{name} must stay inside root")
    if settings.self_file == settings.memory_file:
        raise ConfigError(
            f"[{section_name}].self_file and memory_file must be different"
        )
    return settings


def _build_mcp_section(section_name: str, raw: dict[str, object]) -> "McpSettings":
    known_fields = {
        "enabled",
        "presentation_strategy",
        "max_tool_calls_per_turn",
        "servers",
    }
    unknown_keys = set(raw) - known_fields
    if unknown_keys:
        raise ConfigError(
            f"Unknown key(s) in [{section_name}]: {', '.join(sorted(unknown_keys))}"
        )
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError(
            f"[{section_name}].enabled must be bool, got {type(enabled).__name__}: "
            f"{enabled!r}"
        )
    presentation_strategy = raw.get("presentation_strategy", "native")
    if not isinstance(presentation_strategy, str) or presentation_strategy not in {
        "native",
        "prompt",
    }:
        raise ConfigError(
            f"[{section_name}].presentation_strategy must be 'native' or "
            f"'prompt', got {presentation_strategy!r}"
        )
    max_tool_calls_per_turn = raw.get("max_tool_calls_per_turn", 3)
    if (
        not isinstance(max_tool_calls_per_turn, int)
        or isinstance(max_tool_calls_per_turn, bool)
        or max_tool_calls_per_turn <= 0
    ):
        raise ConfigError(
            f"[{section_name}].max_tool_calls_per_turn must be a positive int, "
            f"got {type(max_tool_calls_per_turn).__name__}: "
            f"{max_tool_calls_per_turn!r}"
        )
    servers = _build_mcp_servers(section_name, raw.get("servers", {}))
    return McpSettings(
        enabled=enabled,
        presentation_strategy=presentation_strategy,
        max_tool_calls_per_turn=max_tool_calls_per_turn,
        servers=servers,
    )


def _build_mcp_servers(section_name: str, raw: object) -> dict[str, McpServerSettings]:
    if not isinstance(raw, dict):
        raise ConfigError(
            f"[{section_name}].servers must be dict, got {type(raw).__name__}: {raw!r}"
        )
    servers: dict[str, McpServerSettings] = {}
    for name, server_raw in raw.items():
        if not isinstance(name, str):
            raise ConfigError(
                f"MCP server keys must be str, got {type(name).__name__}: {name!r}"
            )
        if name == BUILTIN_TOOL_PROVIDER_NAME:
            raise ConfigError(
                f"[{section_name}.servers.{name}] uses reserved provider name "
                f"{BUILTIN_TOOL_PROVIDER_NAME!r}"
            )
        if not isinstance(server_raw, dict):
            raise ConfigError(
                f"[{section_name}.servers.{name}] must be dict, got "
                f"{type(server_raw).__name__}: {server_raw!r}"
            )
        servers[name] = _build_mcp_server(section_name, name, server_raw)
    return servers


def _build_mcp_server(
    section_name: str, name: str, raw: dict[str, object]
) -> McpServerSettings:
    known_fields = {
        "command",
        "args",
        "env",
        "enabled",
        "data_boundary",
        "tool_boundaries",
        "tool_adapters",
    }
    unknown_keys = set(raw) - known_fields
    if unknown_keys:
        raise ConfigError(
            f"Unknown key(s) in [{section_name}.servers.{name}]: "
            f"{', '.join(sorted(unknown_keys))}"
        )
    if "command" not in raw:
        raise ConfigError(f"[{section_name}.servers.{name}].command is required")
    command = raw["command"]
    if not isinstance(command, str) or not command.strip():
        raise ConfigError(
            f"[{section_name}.servers.{name}].command must be a non-empty string"
        )
    args_raw = raw.get("args", [])
    if not isinstance(args_raw, list) or not all(
        isinstance(item, str) for item in args_raw
    ):
        raise ConfigError(
            f"[{section_name}.servers.{name}].args must be a list of strings"
        )
    env_raw = raw.get("env", {})
    if not isinstance(env_raw, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in env_raw.items()
    ):
        raise ConfigError(
            f"[{section_name}.servers.{name}].env must be a table of strings"
        )
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ConfigError(
            f"[{section_name}.servers.{name}].enabled must be bool, got "
            f"{type(enabled).__name__}: {enabled!r}"
        )
    data_boundary = _parse_data_boundary(
        raw.get("data_boundary", DataBoundary.UNKNOWN.value),
        f"[{section_name}.servers.{name}].data_boundary",
    )
    tool_boundaries_raw = raw.get("tool_boundaries", {})
    if not isinstance(tool_boundaries_raw, dict) or not all(
        isinstance(tool_name, str) for tool_name in tool_boundaries_raw
    ):
        raise ConfigError(
            f"[{section_name}.servers.{name}].tool_boundaries must be a table"
        )
    tool_boundaries = {
        tool_name: _parse_data_boundary(
            boundary,
            f"[{section_name}.servers.{name}.tool_boundaries].{tool_name}",
        )
        for tool_name, boundary in tool_boundaries_raw.items()
    }
    tool_adapters = _build_mcp_tool_adapters(
        section_name, name, raw.get("tool_adapters", {})
    )
    return McpServerSettings(
        command=command,
        args=tuple(args_raw),
        env=dict(env_raw),
        enabled=enabled,
        data_boundary=data_boundary,
        tool_boundaries=tool_boundaries,
        tool_adapters=tool_adapters,
    )


def _build_mcp_tool_adapters(
    section_name: str, server_name: str, raw: object
) -> dict[str, McpToolAdapterSettings]:
    location = f"[{section_name}.servers.{server_name}.tool_adapters]"
    if not isinstance(raw, dict):
        raise ConfigError(f"{location} must be a table")

    adapters: dict[str, McpToolAdapterSettings] = {}
    public_names: set[str] = set()
    for upstream_name, adapter_raw in raw.items():
        if not isinstance(upstream_name, str) or not upstream_name.strip():
            raise ConfigError(f"{location} keys must be non-empty strings")
        adapter_location = f"{location[:-1]}.{upstream_name}]"
        if not isinstance(adapter_raw, dict):
            raise ConfigError(f"{adapter_location} must be a table")
        adapter = _build_mcp_tool_adapter(adapter_location, adapter_raw)
        if adapter.public_name in public_names:
            raise ConfigError(
                f"{location} has duplicate canonical tool name {adapter.public_name!r}"
            )
        public_names.add(adapter.public_name)
        adapters[upstream_name] = adapter
    return adapters


def _build_mcp_tool_adapter(
    location: str, raw: dict[str, object]
) -> McpToolAdapterSettings:
    known_fields = {
        "name",
        "description",
        "allowed_arguments",
        "fixed_arguments",
    }
    unknown_keys = set(raw) - known_fields
    if unknown_keys:
        raise ConfigError(
            f"Unknown key(s) in {location}: {', '.join(sorted(unknown_keys))}"
        )

    public_name = raw.get("name")
    if not isinstance(public_name, str) or not public_name.strip():
        raise ConfigError(f"{location}.name must be a non-empty string")
    description = raw.get("description")
    if description is not None and (
        not isinstance(description, str) or not description.strip()
    ):
        raise ConfigError(
            f"{location}.description must be a non-empty string when provided"
        )

    allowed_raw = raw.get("allowed_arguments")
    allowed_arguments: tuple[str, ...] | None = None
    if allowed_raw is not None:
        if not isinstance(allowed_raw, list) or not all(
            isinstance(argument, str) and bool(argument.strip())
            for argument in allowed_raw
        ):
            raise ConfigError(
                f"{location}.allowed_arguments must be a list of non-empty strings"
            )
        if len(set(allowed_raw)) != len(allowed_raw):
            raise ConfigError(
                f"{location}.allowed_arguments must not contain duplicates"
            )
        allowed_arguments = tuple(allowed_raw)

    fixed_raw = raw.get("fixed_arguments", {})
    if not isinstance(fixed_raw, dict) or not all(
        isinstance(key, str)
        and bool(key.strip())
        and isinstance(value, str | int | float | bool)
        for key, value in fixed_raw.items()
    ):
        raise ConfigError(
            f"{location}.fixed_arguments must be a table of JSON scalar values"
        )
    if allowed_arguments is not None:
        overlap = set(allowed_arguments) & set(fixed_raw)
        if overlap:
            raise ConfigError(
                f"{location} arguments cannot be both allowed and fixed: "
                f"{', '.join(sorted(overlap))}"
            )
    return McpToolAdapterSettings(
        public_name=public_name,
        description=description,
        allowed_arguments=allowed_arguments,
        fixed_arguments=dict(fixed_raw),
    )


def _parse_data_boundary(value: object, location: str) -> DataBoundary:
    if not isinstance(value, str):
        raise ConfigError(f"{location} data boundary must be a string")
    try:
        return DataBoundary(value)
    except ValueError:
        allowed = ", ".join(boundary.value for boundary in DataBoundary)
        raise ConfigError(
            f"{location} has unknown data boundary {value!r}; "
            f"expected one of: {allowed}"
        ) from None


def _build_tts_section(section_name: str, raw: dict[str, Any]) -> TtsSettings:
    legacy_fields = set(raw) & {"voice", "rate"}
    if legacy_fields:
        legacy = ", ".join(sorted(legacy_fields))
        raise ConfigError(
            f"Legacy [{section_name}] field(s) {legacy} are no longer supported. "
            "Move voice to [tts.languages.<language>].speaker; configure "
            "engine-specific speed parameters in that language route."
        )
    known_fields = {f.name: f.type for f in fields(TtsSettings)}
    unknown_keys = set(raw) - set(known_fields)
    if unknown_keys:
        raise ConfigError(
            f"Unknown key(s) in [{section_name}]: {', '.join(sorted(unknown_keys))}"
        )

    defaults = TtsSettings()
    kwargs: dict[str, object] = {}
    for name, expected_type in known_fields.items():
        if name == "languages":
            kwargs[name] = _build_tts_languages(raw.get(name, {}), defaults.languages)
            continue
        if name not in raw:
            kwargs[name] = getattr(defaults, name)
            continue
        value = raw[name]
        if not _matches_type(value, expected_type):  # type: ignore[arg-type]
            description = _describe_type(expected_type)  # type: ignore[arg-type]
            raise ConfigError(
                f"[{section_name}].{name} must be {description}, "
                f"got {type(value).__name__}: {value!r}"
            )
        kwargs[name] = value
    return TtsSettings(**kwargs)  # type: ignore[arg-type]


def _build_tts_languages(
    raw: object, defaults: dict[str, TtsLanguageSettings]
) -> dict[str, TtsLanguageSettings]:
    if not isinstance(raw, dict):
        raise ConfigError(
            f"[tts].languages must be dict, got {type(raw).__name__}: {raw!r}"
        )

    routes = dict(defaults)
    for language, route_raw in raw.items():
        if not isinstance(language, str):
            raise ConfigError(
                f"TTS language keys must be str, got {type(language).__name__}: "
                f"{language!r}"
            )
        if language not in SUPPORTED_TTS_LANGUAGES:
            supported = ", ".join(sorted(SUPPORTED_TTS_LANGUAGES))
            raise ConfigError(
                f"Unsupported TTS language in [tts.languages.{language}]: "
                f"{language!r}. Supported languages: {supported}"
            )
        if not isinstance(route_raw, dict):
            raise ConfigError(
                f"[tts.languages.{language}] must be dict, got "
                f"{type(route_raw).__name__}: {route_raw!r}"
            )
        routes[language] = _build_tts_language_route(language, route_raw, routes)
    return routes


def _build_tts_language_route(
    language: str,
    raw: dict[str, object],
    existing_routes: dict[str, TtsLanguageSettings],
) -> TtsLanguageSettings:
    existing = existing_routes.get(language)
    engine = raw.get("engine", existing.engine if existing is not None else None)
    if not isinstance(engine, str):
        raise ConfigError(
            f"[tts.languages.{language}].engine must be str, got "
            f"{type(engine).__name__}: {engine!r}"
        )
    if engine not in SUPPORTED_TTS_ENGINES:
        supported = ", ".join(sorted(SUPPORTED_TTS_ENGINES))
        raise ConfigError(
            f"Unsupported TTS engine in [tts.languages.{language}]: {engine!r}. "
            f"Supported engines: {supported}"
        )

    route_type = SileroTtsSettings if engine == "silero" else PiperTtsSettings
    specs = tts_route_field_specs(engine)
    known_field_names = {spec.name for spec in specs}
    unknown_keys = set(raw) - known_field_names - {"engine"}
    if unknown_keys:
        raise ConfigError(
            f"Unknown key(s) in [tts.languages.{language}]: "
            f"{', '.join(sorted(unknown_keys))}"
        )

    fallback = existing if isinstance(existing, route_type) else None
    if fallback is None and "model" not in raw:
        raise ConfigError(f"[tts.languages.{language}].model is required")

    if route_type is SileroTtsSettings:
        defaults: TtsLanguageSettings = fallback or SileroTtsSettings(model="")
    else:
        defaults = fallback or PiperTtsSettings(model="")
    kwargs: dict[str, object] = {}
    for spec in specs:
        value = raw.get(spec.name, getattr(defaults, spec.name))
        if not tts_field_matches_spec(value, spec):
            raise ConfigError(
                f"[tts.languages.{language}].{spec.name} must be "
                f"{_describe_spec_kind(spec)}, got {type(value).__name__}: "
                f"{value!r}"
            )
        kwargs[spec.name] = value

    route = route_type(**kwargs)  # type: ignore[arg-type]
    validate_tts_route(language, route)
    return route


def validate_tts_route(language: str, route: TtsLanguageSettings) -> None:
    prefix = f"[tts.languages.{language}]"
    for spec in tts_route_field_specs(route.engine):
        value = getattr(route, spec.name)
        if value is None:
            continue
        if spec.non_empty and isinstance(value, str) and not value.strip():
            qualifier = " when set" if spec.nullable else ""
            raise ConfigError(
                f"{prefix}.{spec.name} must be a non-empty string{qualifier}"
            )
        if spec.minimum is None or not isinstance(value, int | float):
            continue
        invalid = (
            value <= spec.minimum if spec.exclusive_minimum else value < spec.minimum
        )
        if invalid:
            comparison = "greater than" if spec.exclusive_minimum else "at least"
            raise ConfigError(
                f"{prefix}.{spec.name} must be {comparison} {spec.minimum}"
            )


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
        if cls is TtsSettings:
            # Let _build_tts_section() produce the deliberate migration
            # message for these removed fields instead of the generic
            # unknown-key error emitted at this file boundary.
            known_fields |= {"voice", "rate"}
        unknown_keys = set(raw.get(section_name, {})) - known_fields
        if unknown_keys:
            raise ConfigError(
                f"Unknown key(s) in [{section_name}] ({source}): "
                f"{', '.join(sorted(unknown_keys))}"
            )


def _merge_raw_section(
    section_name: str, base_section: dict[str, Any], ui_section: dict[str, Any]
) -> dict[str, Any]:
    merged = {**base_section, **ui_section}
    if section_name != "tts":
        return merged

    base_languages = base_section.get("languages", {})
    ui_languages = ui_section.get("languages", {})
    if not isinstance(base_languages, dict) or not isinstance(ui_languages, dict):
        return merged

    languages = {**base_languages}
    for language, ui_route in ui_languages.items():
        base_route = languages.get(language, {})
        if isinstance(base_route, dict) and isinstance(ui_route, dict):
            languages[language] = (
                dict(ui_route) if "engine" in ui_route else {**base_route, **ui_route}
            )
        else:
            languages[language] = ui_route
    merged["languages"] = languages
    return merged


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
            name,
            cls,
            _merge_raw_section(name, base_raw.get(name, {}), ui_raw.get(name, {})),
        )
        for name, cls in _SECTIONS.items()
    }
    return Settings(**kwargs)


def write_ui_config(
    path: str | Path,
    *,
    model: str,
    microphone_device: str,
    ui_language: str | None = None,
    vad: VadSettings | None = None,
    tts_routes: dict[str, TtsLanguageSettings] | None = None,
    mcp_enabled: bool | None = None,
) -> None:
    """Writes config.ui.toml (story-v1.2.4-task-3-config-menu-iteration-1.md:
    "Saving writes only the UI config layer"). This full-snapshot writer is
    used only by the explicit configuration-menu save. It never opens
    config.toml, so it structurally cannot overwrite the human-edited file
    regardless of what path argument it is given.

    Always rewrites the whole machine-owned file. Iteration-2 fields are
    optional: None omits the section entirely, so the layered loader falls
    through to config.toml or the built-in defaults. tts_routes is all-or-
    nothing by contract: a customized [tts.languages] must cover every routed
    language (see tts.py's build_tts_engine), so callers pass either a complete
    route dict or None for the Silero-only default. json.dumps() produces
    quoted, escaped TOML basic strings without a TOML-writing dependency
    (Python's stdlib tomllib is read-only). The live MCP toggle instead uses
    update_ui_config_mcp_enabled() to preserve all unrelated overrides."""
    lines = [
        "# Auto-generated by the Jarvis Status Console. Do not edit by",
        "# hand - saving from the config menu overwrites this file.",
        "[backend]",
        f"model = {json.dumps(model)}",
        "",
        "[microphone]",
        f"device = {json.dumps(microphone_device)}",
    ]
    if ui_language is not None:
        lines += ["", "[ui]", f"language = {json.dumps(ui_language)}"]
    if vad is not None:
        lines += [
            "",
            "[vad]",
            f"threshold = {vad.threshold}",
            f"max_chunk_seconds = {vad.max_chunk_seconds}",
            f"request_end_pause_seconds = {vad.request_end_pause_seconds}",
            f"resume_cooldown_seconds = {vad.resume_cooldown_seconds}",
        ]
    if tts_routes is not None:
        for language in sorted(tts_routes):
            route = tts_routes[language]
            lines += [
                "",
                f"[tts.languages.{language}]",
                f"engine = {json.dumps(route.engine)}",
            ]
            lines.extend(
                f"{name} = {_toml_scalar(value)}"
                for name, value in tts_route_values(route).items()
                if value is not None
            )
    if mcp_enabled is not None:
        lines += ["", "[mcp]", f"enabled = {str(mcp_enabled).lower()}"]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def update_ui_config_mcp_enabled(path: str | Path, *, enabled: bool) -> None:
    """Updates only ``[mcp].enabled`` in the machine-owned UI layer."""
    path = Path(path)
    if not path.exists():
        path.write_text(
            "# Auto-generated by the Jarvis Status Console. Do not edit by\n"
            "# hand - saving from the config menu overwrites this file.\n"
            "[mcp]\n"
            f"enabled = {str(enabled).lower()}\n",
            encoding="utf-8",
        )
        return

    raw = _read_toml_file(path)
    _validate_raw_config(raw, path)
    contents = path.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in contents else "\n"
    lines = contents.splitlines(keepends=True)
    section_start, section_end, first_nested_section = _find_mcp_section(lines)
    value = str(enabled).lower()

    if section_start is None:
        insertion = (
            first_nested_section if first_nested_section is not None else len(lines)
        )
        _insert_mcp_section(lines, insertion, value, newline)
    else:
        _set_mcp_enabled(lines, section_start, section_end, value, newline)
    path.write_bytes("".join(lines).encode("utf-8"))


def _find_mcp_section(lines: list[str]) -> tuple[int | None, int, int | None]:
    section_start: int | None = None
    section_end = len(lines)
    first_nested_section: int | None = None
    for index, line in enumerate(lines):
        match = _TOML_SECTION_LINE.match(line)
        if match is None:
            continue
        name = match.group("name")
        if name == "mcp":
            section_start = index
            continue
        if name.startswith("mcp.") and first_nested_section is None:
            first_nested_section = index
        if section_start is not None:
            section_end = index
            break
    return section_start, section_end, first_nested_section


def _insert_mcp_section(
    lines: list[str], insertion: int, value: str, newline: str
) -> None:
    if insertion > 0 and not lines[insertion - 1].endswith(("\n", "\r")):
        lines[insertion - 1] += newline
    if insertion > 0 and lines[insertion - 1].strip():
        lines.insert(insertion, newline)
        insertion += 1
    lines.insert(insertion, f"[mcp]{newline}enabled = {value}{newline}")


def _set_mcp_enabled(
    lines: list[str],
    section_start: int,
    section_end: int,
    value: str,
    newline: str,
) -> None:
    for index in range(section_start + 1, section_end):
        match = _TOML_ENABLED_LINE.match(lines[index])
        if match is None:
            continue
        line_ending = newline if lines[index].endswith(("\n", "\r")) else ""
        lines[index] = f"{match.group('indent')}enabled = {value}{line_ending}"
        return

    if section_end > 0 and not lines[section_end - 1].endswith(("\n", "\r")):
        lines[section_end - 1] += newline
    lines.insert(section_end, f"enabled = {value}{newline}")


def _toml_scalar(value: TtsFieldValue) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int | float):
        return str(value)
    raise TypeError("None values must be omitted before TOML serialization")
