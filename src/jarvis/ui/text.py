"""Per-language catalog of UI-visible runtime strings.

Story story-v1.2.11-ui-english-localization.md: every string the Status
Console or Touchstrip can display that is produced on the Python side
lives here, in one catalog keyed by UI language. The runtime resolves
strings through this module using [ui].language from config.py; nothing
outside this module hardcodes UI-visible prose.

Boundary: this is UI chrome only. The dialog language - the Russian
system prompt, TTS output, and speech markup - is runtime data, not UI
text, and is deliberately not represented here.
"""

from jarvis.ui.contract import ModuleId, RuntimeState

SUPPORTED_UI_LANGUAGES = ("en", "ru")
DEFAULT_UI_LANGUAGE = "en"

# Labels/default substatus text for each RuntimeState. Kept out of app.js
# so the mapping is covered by a pure Python test and localizes in one
# place (see status_console.runtime_state_payload()).
_RUNTIME_STATE_TEXT: dict[str, dict[RuntimeState, tuple[str, str]]] = {
    "en": {
        RuntimeState.IDLE: ("Idle", 'Say "Jarvis" to begin.'),
        RuntimeState.WARMING: (
            "Warming up (local)",
            "Loading the model into GPU memory...",
        ),
        RuntimeState.LISTENING: ("Ready", "Waiting for a request"),
        RuntimeState.THINKING: (
            "Thinking",
            "Gathering context and composing a response...",
        ),
        RuntimeState.SPEAKING: ("Speaking", "Speaking the response aloud..."),
        RuntimeState.ERROR: ("Error", ""),
    },
    "ru": {
        RuntimeState.IDLE: ("Ожидание", "Скажите «Джарвис», чтобы начать."),
        RuntimeState.WARMING: (
            "Прогрев (локально)",
            "Модель загружается в память GPU...",
        ),
        RuntimeState.LISTENING: ("Готов", "Ожидаю запрос"),
        RuntimeState.THINKING: ("Думаю", "Собираю контекст и формирую ответ..."),
        RuntimeState.SPEAKING: ("Отвечаю", "Произношу ответ вслух..."),
        RuntimeState.ERROR: ("Ошибка", ""),
    },
}

# Genitive-friendly module names used inside the module-reset message.
_MODULE_LABELS: dict[str, dict[ModuleId, str]] = {
    "en": {
        ModuleId.BACKEND: "model/backend",
        ModuleId.MICROPHONE: "microphone",
        ModuleId.TTS: "TTS",
        ModuleId.MEMORY: "memory",
        ModuleId.VISION: "vision/screen",
    },
    "ru": {
        ModuleId.BACKEND: "модели/backend",
        ModuleId.MICROPHONE: "микрофона",
        ModuleId.TTS: "TTS",
        ModuleId.MEMORY: "памяти",
        ModuleId.VISION: "vision/экрана",
    },
}

_MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        # Runtime substatus lines pushed by main.py/ui_transport.py.
        "warming_model": "Warming up the model...",
        "ready_to_listen": "Waiting for a request",
        "processing_voice": "Processing voice...",
        "processing_text": "Processing text...",
        "processing_attachment": "Processing attachment...",
        "speaking_response": "Speaking the response...",
        # Microphone module-health details. "not in use" (user-muted) is
        # the wording settled by story-v1.2.10-task-5-ui-cosmetic-polish.md.
        "mic_detail_listening": "listening",
        "mic_detail_muted": "not in use",
        # Module-health details published by ModuleHealthTracker.
        "backend_detail_ready": "responding",
        "backend_detail_warmup_failed": "warm-up failed",
        "backend_detail_request_failed": "request failed",
        "tts_detail_ready": "speaking",
        "tts_detail_failed": "synthesis failed",
        "tts_detail_load_failed": "engine load failed",
        "vision_detail_ready": "capture ok",
        "vision_detail_failed": "capture failed",
        # System event ui_message strings.
        "context_reset": "Conversation context reset",
        "module_reset_unsupported": (
            "Reset of {module} requested, but not supported by the engine yet"
        ),
        "hidden_mode_enabled": "Hidden mode activated: screen preview is hidden",
        "open_mode_restored": "Open mode restored",
        "shutdown_requested": "Jarvis shutdown requested",
        "model_options_failed": (
            "Failed to fetch the Ollama model list - showing the current value"
        ),
        "microphone_options_failed": (
            "Failed to fetch the microphone list - showing the current value"
        ),
        "config_save_rejected_no_model": "Save cancelled: no model selected",
        "config_save_rejected_invalid": (
            "Save cancelled: some settings values are invalid"
        ),
        "config_saved_restart_to_apply": "Settings saved - restart Jarvis to apply",
        "warmup_failed": "Model warm-up failed - the first response may be slow",
        "warmup_succeeded": "Model warm-up complete",
        "mic_awake": "Microphone woken up",
        "mic_asleep": "Microphone put to sleep",
        "reasoning_level_off": "Reasoning level: off",
        "reasoning_level_low": "Reasoning level: low",
        "reasoning_level_medium": "Reasoning level: medium",
        "reasoning_level_high": "Reasoning level: high",
        # MCP host/interception system events (story-v1.4.0 task 3).
        "mcp_enabled": "MCP enabled",
        "mcp_enabled_degraded": "MCP enabled (not everything connected)",
        "mcp_disabled": "MCP disabled",
        "mcp_server_unavailable": "Server {server} is unavailable",
        "mcp_server_disconnect_failed": "Error disconnecting server {server}",
        "mcp_tool_name_collision": "Tool name collision: {tool} ({server})",
        "mcp_server_call_failed": (
            "Server {server} failed during a tool call and was marked unavailable"
        ),
        "mcp_calling_tool": "Calling tool {tool} ({provider}): {summary}",
        "mcp_tool_call_failed": "Tool {tool} failed ({duration:.1f}s)",
        "mcp_tool_call_finished": "{tool} ({provider}) finished in {duration:.1f}s",
        "mcp_tool_call_cancelled": "Tool {tool} ({provider}) call was cancelled",
        "mcp_call_rejected_disabled": "Tool call to {tool} rejected: MCP is disabled",
        "mcp_call_rejected_unknown_tool": "Tool call rejected: unknown tool {tool}",
        "mcp_call_rejected_tool_disabled": "Tool call rejected: {tool} is disabled",
        "mcp_call_rejected_arguments": (
            "Tool call rejected: {tool} received unsupported arguments"
        ),
        "mcp_call_rejected_provider_not_connected": (
            "Tool call to {tool} rejected: provider {provider} is not connected"
        ),
        "mcp_tool_adapter_rejected": (
            "MCP server {server} does not match its configured tool adapter"
        ),
    },
    "ru": {
        "warming_model": "Прогреваю модель...",
        "ready_to_listen": "Ожидаю запрос",
        "processing_voice": "Обрабатываю голос...",
        "processing_text": "Обрабатываю текст...",
        "processing_attachment": "Обрабатываю вложение...",
        "speaking_response": "Произношу ответ...",
        "mic_detail_listening": "слушает",
        "mic_detail_muted": "не используется",
        "backend_detail_ready": "отвечает",
        "backend_detail_warmup_failed": "прогрев не удался",
        "backend_detail_request_failed": "сбой запроса",
        "tts_detail_ready": "озвучивает",
        "tts_detail_failed": "сбой синтеза",
        "tts_detail_load_failed": "сбой загрузки движка",
        "vision_detail_ready": "захват в норме",
        "vision_detail_failed": "сбой захвата",
        "context_reset": "Контекст диалога сброшен",
        "module_reset_unsupported": (
            "Сброс {module} запрошен, но пока не поддерживается движком"
        ),
        "hidden_mode_enabled": "Режим Hidden активирован: превью экрана скрыто",
        "open_mode_restored": "Режим Open восстановлен",
        "shutdown_requested": "Запрошено завершение работы Jarvis",
        "model_options_failed": (
            "Не удалось получить список моделей Ollama - показано текущее значение"
        ),
        "microphone_options_failed": (
            "Не удалось получить список микрофонов - показано текущее значение"
        ),
        "config_save_rejected_no_model": "Сохранение отменено: модель не выбрана",
        "config_save_rejected_invalid": (
            "Сохранение отменено: часть значений настроек недопустима"
        ),
        "config_saved_restart_to_apply": (
            "Настройки сохранены - перезапустите Jarvis, чтобы применить"
        ),
        "warmup_failed": "Прогрев модели не удался - первый ответ может быть медленным",
        "warmup_succeeded": "Прогрев модели завершён",
        "mic_awake": "Микрофон разбужен",
        "mic_asleep": "Микрофон усыплён",
        "reasoning_level_off": "Уровень мышления: выключен",
        "reasoning_level_low": "Уровень мышления: низкий",
        "reasoning_level_medium": "Уровень мышления: средний",
        "reasoning_level_high": "Уровень мышления: высокий",
        "mcp_enabled": "MCP включён",
        "mcp_enabled_degraded": "MCP включён (не всё подключилось)",
        "mcp_disabled": "MCP выключен",
        "mcp_server_unavailable": "Сервер «{server}» недоступен",
        "mcp_server_disconnect_failed": "Ошибка отключения сервера «{server}»",
        "mcp_tool_name_collision": "Конфликт имён инструментов: «{tool}» ({server})",
        "mcp_server_call_failed": (
            "Сервер «{server}» отказал во время вызова инструмента и помечен "
            "недоступным"
        ),
        "mcp_calling_tool": "Вызов инструмента «{tool}» ({provider}): {summary}",
        "mcp_tool_call_failed": (
            "Инструмент «{tool}» завершился с ошибкой ({duration:.1f} с)"
        ),
        "mcp_tool_call_finished": "«{tool}» ({provider}) завершён за {duration:.1f} с",
        "mcp_tool_call_cancelled": "Вызов «{tool}» ({provider}) отменён",
        "mcp_call_rejected_disabled": "Вызов «{tool}» отклонён: MCP выключен",
        "mcp_call_rejected_unknown_tool": (
            "Вызов отклонён: неизвестный инструмент «{tool}»"
        ),
        "mcp_call_rejected_tool_disabled": "Вызов отклонён: «{tool}» отключён",
        "mcp_call_rejected_arguments": (
            "Вызов отклонён: «{tool}» получил неподдерживаемые аргументы"
        ),
        "mcp_call_rejected_provider_not_connected": (
            "Вызов «{tool}» отклонён: провайдер «{provider}» не подключён"
        ),
        "mcp_tool_adapter_rejected": (
            "MCP-сервер {server} не соответствует настроенному адаптеру инструментов"
        ),
    },
}


def runtime_state_text(
    state: RuntimeState, language: str = DEFAULT_UI_LANGUAGE
) -> tuple[str, str]:
    return _RUNTIME_STATE_TEXT[language][state]


def module_label(module: ModuleId, language: str = DEFAULT_UI_LANGUAGE) -> str:
    return _MODULE_LABELS[language][module]


def ui_text(
    key: str,
    language: str = DEFAULT_UI_LANGUAGE,
    **format_args: str | int | float,
) -> str:
    return _MESSAGES[language][key].format(**format_args)
