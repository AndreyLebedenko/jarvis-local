// Static-text dictionary for the web UI surfaces (story-v1.2.11).
//
// Loaded before transport.js/app.js/touchstrip.js so every layer can look
// up text through uiString(). The active language starts as English (the
// project default) and is switched by applyUiLanguage() when the engine
// snapshot delivers state.ui_language - the Python side owns the setting
// ([ui].language in config.py), this file only renders it.
//
// HTML elements carry data-i18n="key" (text content) or
// data-i18n-title="key" (title attribute); applyUiLanguage() re-stamps
// them all, so the pre-transport English markup and the post-snapshot
// language always agree with one dictionary, never two copies.

const UI_STRINGS = {
  en: {
    locality_local: "Local",
    locality_external: "External backend",
    chip_model: "Model",
    chip_microphone: "Microphone",
    chip_tts: "TTS",
    chip_memory: "Memory",
    chip_vision: "Vision",
    chip_reset_backend: "Request model/backend reset",
    chip_reset_microphone: "Request microphone reset",
    chip_reset_tts: "Request TTS reset",
    chip_reset_memory: "Request memory reset",
    chip_reset_vision: "Request vision/screen reset",
    think_title: "Thinking mode",
    think_status_on: "Deeper, slower - with extended request processing",
    think_status_off: "Faster, without reasoning",
    btn_settings: "⚙ Settings",
    btn_reset_context: "Reset context",
    btn_shutdown: "Shut down",
    confirm_reset_text: "The dialog and current context will be deleted. This cannot be undone.",
    confirm_shutdown_text: "Jarvis will be stopped. You will need to start the process again.",
    btn_cancel: "Cancel",
    btn_confirm_reset: "Reset",
    btn_confirm_shutdown: "Shut down",
    config_model_label: "Model",
    config_microphone_label: "Microphone",
    btn_apply: "Apply",
    pending_restart_text: "Changes saved - restart Jarvis to apply.",
    default_microphone_option: "(system default microphone)",
    log_title: "System events",
    log_sub: "engine log - real time",
    log_empty: "No events yet",
    legend_info: "info",
    legend_active: "active",
    legend_warn: "warning",
    legend_error: "error",
    vision_preview_hidden: "preview hidden (Hidden)",
    transport_no_connection: "No connection to engine",
    transport_no_token: "No UI transport token in URL",
    transport_data_error: "UI transport data error",
    strip_locality_local: "local",
    strip_locality_external: "external backend",
    strip_think_label: "Thinking",
    strip_reset_hold_hint: "hold 1s to confirm",
    strip_shutdown_hold_hint: "hold 2s to confirm",
  },
  ru: {
    locality_local: "Локально",
    locality_external: "Внешний backend",
    chip_model: "Модель",
    chip_microphone: "Микрофон",
    chip_tts: "TTS",
    chip_memory: "Память",
    chip_vision: "Vision",
    chip_reset_backend: "Запросить сброс модели/backend",
    chip_reset_microphone: "Запросить сброс микрофона",
    chip_reset_tts: "Запросить сброс TTS",
    chip_reset_memory: "Запросить сброс памяти",
    chip_reset_vision: "Запросить сброс vision/экрана",
    think_title: "Режим мышления",
    think_status_on: "Глубже, медленнее - с расширенной обработкой запроса",
    think_status_off: "Быстрее, без рассуждения",
    btn_settings: "⚙ Настройки",
    btn_reset_context: "Сбросить контекст",
    btn_shutdown: "Завершить работу",
    confirm_reset_text: "Диалог и текущий контекст будут удалены. Отменить нельзя.",
    confirm_shutdown_text: "Jarvis будет остановлен. Потребуется запустить процесс заново.",
    btn_cancel: "Отмена",
    btn_confirm_reset: "Сбросить",
    btn_confirm_shutdown: "Завершить",
    config_model_label: "Модель",
    config_microphone_label: "Микрофон",
    btn_apply: "Применить",
    pending_restart_text: "Изменения сохранены - перезапустите Jarvis, чтобы применить.",
    default_microphone_option: "(системный микрофон по умолчанию)",
    log_title: "События системы",
    log_sub: "engine log - реальное время",
    log_empty: "Пока нет событий",
    legend_info: "инфо",
    legend_active: "активно",
    legend_warn: "предупреждение",
    legend_error: "ошибка",
    vision_preview_hidden: "превью скрыто (Hidden)",
    transport_no_connection: "Нет связи с engine",
    transport_no_token: "Нет токена UI transport в URL",
    transport_data_error: "Ошибка данных UI transport",
    strip_locality_local: "локально",
    strip_locality_external: "внешний backend",
    strip_think_label: "Мышление",
    strip_reset_hold_hint: "удержать 1с для подтверждения",
    strip_shutdown_hold_hint: "удержать 2с для подтверждения",
  },
};

const DEFAULT_UI_LANGUAGE = "en";
let _uiLanguage = DEFAULT_UI_LANGUAGE;

function uiString(key) {
  const catalog = UI_STRINGS[_uiLanguage] || UI_STRINGS[DEFAULT_UI_LANGUAGE];
  const text = catalog[key];
  if (text === undefined) {
    throw new Error("Unknown UI string key: " + key);
  }
  return text;
}

function currentUiLanguage() {
  return _uiLanguage;
}

// Called from the snapshot/delta handlers with state.ui_language. The
// language never changes mid-session on the Python side (config is
// restart-to-apply), so in practice this runs once per connection - but
// re-stamping is idempotent either way.
function applyUiLanguage(payload) {
  const language = payload && payload.language;
  if (!Object.prototype.hasOwnProperty.call(UI_STRINGS, language)) return;
  _uiLanguage = language;
  document.documentElement.setAttribute("lang", language);
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    element.textContent = uiString(element.getAttribute("data-i18n"));
  });
  document.querySelectorAll("[data-i18n-title]").forEach((element) => {
    element.title = uiString(element.getAttribute("data-i18n-title"));
  });
}
