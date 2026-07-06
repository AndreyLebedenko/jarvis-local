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
}

buildControls();
for (const module of ["backend", "microphone", "tts", "memory", "vision"]) {
  applyModuleHealth({ module, status: "ok", detail: "demo:ok" });
}
applyModelLabel({ label: "gemma4:12b-it-qat (demo)" });
