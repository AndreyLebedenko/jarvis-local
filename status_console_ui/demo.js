// Demo/QA harness wiring for demo.html - not part of the production shell.
// Builds one button per RuntimeState/HealthStatus/DataLocality value and
// calls the exact same app.js functions status_console.py's evaluate_js
// bridge would call, so this exercises the real rendering path.

const RUNTIME_STATE_LABELS = {
  idle: ["Ожидание", "Скажите «Джарвис», чтобы начать."],
  warming: ["Прогрев (локально)", "Модель загружается в память GPU..."],
  listening: ["Слушаю", "Жду голосовую команду..."],
  thinking: ["Думаю", "Собираю контекст и формирую ответ..."],
  speaking: ["Отвечаю", "Произношу ответ вслух..."],
  error: ["Ошибка", "Смотри событие в логе (task-ui-03)."],
};

function buildControls() {
  const root = document.getElementById("demoControls");

  const stateGroup = document.createElement("span");
  stateGroup.textContent = "state:";
  root.appendChild(stateGroup);
  for (const state of Object.keys(RUNTIME_STATE_LABELS)) {
    const [label, sub] = RUNTIME_STATE_LABELS[state];
    const button = document.createElement("button");
    button.textContent = state;
    button.onclick = () => applyRuntimeState({ state, label, substatus: sub });
    root.appendChild(button);
  }

  const moduleGroup = document.createElement("span");
  moduleGroup.textContent = "backend health:";
  root.appendChild(moduleGroup);
  for (const status of ["ok", "degraded", "error", "unavailable"]) {
    const button = document.createElement("button");
    button.textContent = status;
    button.onclick = () =>
      applyModuleHealth({ module: "backend", status, detail: "demo:" + status });
    root.appendChild(button);
  }

  const localityGroup = document.createElement("span");
  localityGroup.textContent = "locality:";
  root.appendChild(localityGroup);
  for (const locality of ["local", "external"]) {
    const button = document.createElement("button");
    button.textContent = locality;
    button.onclick = () => applyDataLocality({ locality });
    root.appendChild(button);
  }

  const logGroup = document.createElement("span");
  logGroup.textContent = "log event:";
  root.appendChild(logGroup);
  const sampleMessages = {
    info: ["ENGINE", "Цикл завершён"],
    active: ["LLM", "Запрос отправлен в Ollama"],
    warn: ["WARMUP", "Прогрев не удался - первый ответ может быть медленным"],
    error: ["TTS", "Устройство вывода звука не найдено"],
  };
  for (const level of EVENT_LEVELS) {
    const [source, message] = sampleMessages[level];
    const button = document.createElement("button");
    button.textContent = level;
    button.onclick = () =>
      appendSystemEvent({ timestamp: Date.now() / 1000, source, level, message });
    root.appendChild(button);
  }

  const stressButton = document.createElement("button");
  stressButton.textContent = "+50 events";
  stressButton.title = "Stress-test long-message wrapping and MAX_LOG_ENTRIES trimming";
  stressButton.onclick = () => {
    for (let i = 0; i < 50; i++) {
      appendSystemEvent({
        timestamp: Date.now() / 1000,
        source: "ENGINE",
        level: EVENT_LEVELS[i % EVENT_LEVELS.length],
        message:
          i % 7 === 0
            ? "Очень длинное сообщение для проверки переноса строки в узкой панели событий без поломки раскладки: " +
              "eval_count=163 prompt_eval_duration=1.2s load_duration=0.3s"
            : `Событие #${i}`,
      });
    }
  };
  root.appendChild(stressButton);

  // window.pywebview does not exist in a plain browser, so toggleThinking()'s
  // real click handler (index.html/app.js) is a guarded no-op here - these
  // buttons call applyThinkingMode() directly to exercise the switch's
  // visual/animation without a live backend.
  const thinkGroup = document.createElement("span");
  thinkGroup.textContent = "think switch:";
  root.appendChild(thinkGroup);
  for (const isEnabled of [true, false]) {
    const button = document.createElement("button");
    button.textContent = isEnabled ? "on" : "off";
    button.onclick = () => applyThinkingMode({ is_enabled: isEnabled });
    root.appendChild(button);
  }

  // Same reasoning as the think-switch buttons above: the real
  // #visibilityToggle buttons call setVisibilityMode(), a guarded no-op
  // here without window.pywebview - these call applyVisibilityMode()
  // directly to exercise the toggle/vision-chip-hiding visuals.
  const visibilityGroup = document.createElement("span");
  visibilityGroup.textContent = "visibility:";
  root.appendChild(visibilityGroup);
  for (const mode of VISIBILITY_MODES) {
    const button = document.createElement("button");
    button.textContent = mode;
    button.onclick = () => applyVisibilityMode({ mode });
    root.appendChild(button);
  }

  const visionDetailButton = document.createElement("button");
  visionDetailButton.textContent = "set vision detail";
  visionDetailButton.title = "Simulate a real capture detail arriving, to check Hidden hides it";
  visionDetailButton.onclick = () =>
    applyModuleHealth({ module: "vision", status: "ok", detail: "1200x800 @ 14:22:07" });
  root.appendChild(visionDetailButton);
}

buildControls();
for (const module of ["backend", "microphone", "tts", "memory", "vision"]) {
  applyModuleHealth({ module, status: "ok", detail: "demo:ok" });
}
applyModelLabel({ label: "gemma4:12b-it-qat (demo)" });
