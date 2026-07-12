// Demo/QA harness wiring for demo.html - not part of the production shell.
// Builds one button per RuntimeState/HealthStatus/DataLocality value and
// calls the exact same app.js rendering functions as the live transport client
// bridge would call, so this exercises the real rendering path.

const RUNTIME_STATE_LABELS = {
  idle: ["Idle", 'Say "Jarvis" to begin.'],
  warming: ["Warming up (local)", "Loading the model into GPU memory..."],
  listening: ["Ready", "Waiting for a request"],
  thinking: ["Thinking", "Gathering context and composing a response..."],
  speaking: ["Speaking", "Speaking the response aloud..."],
  error: ["Error", "See the event in the log (task-ui-03)."],
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

  const requestGroup = document.createElement("span");
  requestGroup.textContent = "last request:";
  root.appendChild(requestGroup);
  const requestSamples = [
    {
      label: "voice",
      payload: { timestamp: Date.now() / 1000, items: [{ kind: "audio", duration_seconds: 4.2 }] },
    },
    {
      label: "voice + screenshot",
      payload: {
        timestamp: Date.now() / 1000,
        items: [{ kind: "audio", duration_seconds: 4.2 }, { kind: "screenshot" }],
      },
    },
    {
      label: "clipboard",
      payload: { timestamp: Date.now() / 1000, items: [{ kind: "clipboard" }] },
    },
  ];
  for (const sample of requestSamples) {
    const button = document.createElement("button");
    button.textContent = sample.label;
    button.onclick = () => applyLastModelRequest({ ...sample.payload, timestamp: Date.now() / 1000 });
    root.appendChild(button);
  }

  const logGroup = document.createElement("span");
  logGroup.textContent = "log event:";
  root.appendChild(logGroup);
  const sampleMessages = {
    info: ["ENGINE", "Cycle complete"],
    active: ["LLM", "Request sent to Ollama"],
    warn: ["WARMUP", "Warm-up failed - the first response may be slow"],
    error: ["TTS", "Audio output device not found"],
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
            ? "A very long message to check line wrapping in the narrow event panel without breaking the layout: " +
              "eval_count=163 prompt_eval_duration=1.2s load_duration=0.3s"
            : `Event #${i}`,
      });
    }
  };
  root.appendChild(stressButton);

  // The demo has no live UI transport, so toggleThinking()'s real click
  // handler is a no-op here - these
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
  // #visibilityToggle buttons call setVisibilityMode(), a no-op here without
  // a live UI transport - these call applyVisibilityMode()
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

  // story-v1.2.4-task-3: config menu. Same reasoning as the think-switch/
  // visibility buttons above - the real request_model_options()/
  // request_microphone_options()/save_config_selection() are guarded
  // no-ops without a live UI transport, so these call the apply*() functions
  // directly to exercise the dropdown-population and pending-restart
  // visuals without a live Ollama endpoint or real audio devices.
  const configGroup = document.createElement("span");
  configGroup.textContent = "config menu:";
  root.appendChild(configGroup);

  const modelOptionsButton = document.createElement("button");
  modelOptionsButton.textContent = "model options";
  modelOptionsButton.onclick = () =>
    applyModelOptions({ options: ["gemma4:12b-it-qat", "llama3:8b"], current: "gemma4:12b-it-qat" });
  root.appendChild(modelOptionsButton);

  const micOptionsButton = document.createElement("button");
  micOptionsButton.textContent = "mic options";
  micOptionsButton.onclick = () =>
    applyMicrophoneOptions({ options: ["", "USB Headset", "Built-in Microphone"], current: "" });
  root.appendChild(micOptionsButton);

  const degradedOptionsButton = document.createElement("button");
  degradedOptionsButton.textContent = "options degraded";
  degradedOptionsButton.title = "Simulate enumeration failure - options collapse to current value only";
  degradedOptionsButton.onclick = () => {
    applyModelOptions({ options: ["gemma4:12b-it-qat"], current: "gemma4:12b-it-qat" });
    applyMicrophoneOptions({ options: [""], current: "" });
  };
  root.appendChild(degradedOptionsButton);

  for (const pending of [true, false]) {
    const button = document.createElement("button");
    button.textContent = "pending restart: " + pending;
    button.onclick = () => applyPendingRestart({ pending });
    root.appendChild(button);
  }

  // story-v1.3.0-task-2: configuration iteration 2 values, mirroring the
  // config_values_payload() shape from status_console.py.
  const configValuesButton = document.createElement("button");
  configValuesButton.textContent = "config values (default)";
  configValuesButton.onclick = () => applyConfigValues(_demoConfigValues(false));
  root.appendChild(configValuesButton);

  const configRoutesButton = document.createElement("button");
  configRoutesButton.textContent = "config values (bilingual)";
  configRoutesButton.onclick = () => applyConfigValues(_demoConfigValues(true));
  root.appendChild(configRoutesButton);
}

function _demoConfigValues(bilingual) {
  const schemas = {
    silero: [
      _demoTtsSpec("model", "string", false, true, "v3_1_ru", true),
      _demoTtsSpec("language", "string", false, false, "ru", true),
      _demoTtsSpec("speaker", "string", false, false, "baya", true),
      _demoTtsSpec("sample_rate", "integer", false, false, 48000, false, 0, true),
      _demoTtsSpec("put_accent", "boolean", true, false, null),
      _demoTtsSpec("put_yo", "boolean", true, false, null),
    ],
    piper: [
      _demoTtsSpec("model", "string", false, true, null, true),
      _demoTtsSpec("config_path", "string", true, false, null, true),
      _demoTtsSpec("use_cuda", "boolean", false, false, false),
      _demoTtsSpec("espeak_data_dir", "string", true, false, null, true),
      _demoTtsSpec("download_dir", "string", true, false, null, true),
      _demoTtsSpec("speaker_id", "integer", true, false, null, false, 0),
      _demoTtsSpec("length_scale", "number", true, false, null, false, 0, true),
      _demoTtsSpec("noise_scale", "number", true, false, null, false, 0, true),
      _demoTtsSpec("noise_w_scale", "number", true, false, null, false, 0, true),
      _demoTtsSpec("normalize_audio", "boolean", false, false, true),
      _demoTtsSpec("volume", "number", false, false, 1.0, false, 0, true),
    ],
  };
  const routes = {
    ru: {
      engine: "silero", model: "v3_1_ru", language: "ru", speaker: "baya",
      sample_rate: 48000, put_accent: null, put_yo: null,
    },
  };
  if (bilingual) {
    routes.en = {
      engine: "piper", model: "C:/voices/en.onnx", config_path: null,
      use_cuda: false, espeak_data_dir: null, download_dir: null,
      speaker_id: null, length_scale: 1.0, noise_scale: 0.667,
      noise_w_scale: 0.8, normalize_audio: true, volume: 1.0,
    };
  }
  return {
    ui_language: "en",
    ui_language_options: ["en", "ru"],
    vad: {
      threshold: 0.5,
      max_chunk_seconds: 30,
      request_end_pause_seconds: 2.0,
      resume_cooldown_seconds: 1.0,
    },
    vad_ranges: {
      threshold: [0.0, 1.0],
      max_chunk_seconds: [1, 120],
      request_end_pause_seconds: [0.1, 10.0],
      resume_cooldown_seconds: [0.0, 10.0],
    },
    tts: {
      languages: ["en", "ru"],
      engines: ["piper", "silero"],
      schemas,
      routes,
    },
  };
}

function _demoTtsSpec(
  name, kind, nullable, required, defaultValue, nonEmpty = false,
  minimum = null, exclusiveMinimum = false
) {
  return {
    name, kind, nullable, required, default: defaultValue, non_empty: nonEmpty,
    minimum, exclusive_minimum: exclusiveMinimum,
  };
}

buildControls();
for (const module of ["backend", "microphone", "tts", "memory", "vision"]) {
  applyModuleHealth({ module, status: "ok", detail: "demo:ok" });
}
applyModelLabel({ label: "gemma4:12b-it-qat (demo)" });
applyLastModelRequest({
  timestamp: Date.now() / 1000,
  items: [{ kind: "audio", duration_seconds: 4.2 }],
});
applyModelOptions({
  options: ["gemma4:12b-it-qat", "llama3:8b"],
  current: "gemma4:12b-it-qat",
});
applyMicrophoneOptions({ options: ["", "USB Headset"], current: "" });
applyConfigValues(_demoConfigValues(true));
