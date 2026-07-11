# Story: Status Console UI

**Статус:** Completed.
**Родитель:** future UI roadmap
**Связано с:** task-ui-privacy-and-touchstrip-requirements.md,
backlog/activation-warmup.md, story-v1.2.6-hotkey-provider-migration.md
**Дата создания:** 2026-07-06

## Контекст

Jarvis до v1.1.1 был background process с hotkeys, sound cues и console logs.
Это удобно для быстрых voice turns, но плохо отвечает на вопросы пользователя:
жив ли Jarvis, что он сейчас делает, включен ли Think, слышит ли микрофон,
почему нет ответа, была ли ошибка TTS или backend.

Нужна первая GUI-панель не как полноценный control center, а как Status
Console: компактное окно состояния, минимальные controls и видимый system log.

## Цель

Дать пользователю быстрый ответ на три вопроса:

1. Что Jarvis делает прямо сейчас?
2. Какие ключевые модули доступны или сломаны?
3. Что произошло в engine без необходимости читать Windows console?

## Product Boundary

В первую версию входят:

- runtime state: `IDLE`, `WARMING`, `LISTENING`, `THINKING`, `SPEAKING`,
  `ERROR`;
- module status chips: backend/model, microphone, TTS, memory, vision/screen;
- Think toggle state and control;
- global context reset and per-module reset commands;
- system events panel;
- data locality indicator for supported backend mode;
- system visibility mode: `Open` / `Hidden`;
- touchstrip-compatible glance/control surface requirements.

В первую версию не входят:

- cloud provider switching;
- memory browser/editor;
- plugin marketplace/settings;
- full transcript/history window;
- visible reasoning traces;
- dense resource dashboard as the primary screen.

## Key Decisions

- UI consumes engine state through explicit events/snapshots. It must not parse
  console output.
- `Open` / `Hidden` is a system visibility mode, not a description of where
  the user physically is.
- Data locality and system visibility are separate axes in UI and events.
- `WARMING` is a runtime state. It must not look like cloud/network warning.
- Think mode exposes enabled/disabled state only. Reasoning text is not shown.
- Reset controls must be explicit about what is being reset.

## Acceptance Criteria

- [x] Status Console can show all runtime states, including `WARMING` and
      `ERROR`.
- [x] System events visible in UI include timestamp, source, level and message.
- [x] Think toggle mirrors existing `ThinkingModeState` behavior and keeps the
      same turn-start sampling semantics.
- [x] Reset actions are routed through engine APIs/events, not local UI-only
      state changes.
- [x] `Open` / `Hidden` changes have clear, testable effects on TTS/screen
      preview visibility.
- [x] Touchstrip surface has its own layout rules and is not a squeezed
      desktop dashboard.
- [x] No UI path introduces network dependency into Jarvis core.

## Open Questions

- ~~Which GUI framework is the first implementation target?~~ **Resolved
  (human decision, task-ui-02):** `pywebview` over a local HTML/CSS/JS
  front-end. Windows backend is WebView2 (pre-installed on Win11); a future
  Linux backend would be QtWebEngine via PySide6 - a `pywebview` GUI backend
  choice, not a UI rewrite. All fonts/assets are local, no CDN. The UI is a
  thin client over engine state delivered through pywebview's own in-process
  bridge (`evaluate_js`/`js_api`); a networked WebSocket layer is deferred to
  whichever later task needs cross-device delivery (e.g. task-ui-06's
  touchstrip, if it ends up running on a separate device).
- **Deferred:** Should Status Console be always-on-top by default or opt-in?
  The first implementation leaves it as a normal window; changing window
  policy is a later UX decision, not required for this story's accepted scope.
- ~~Does `Hidden` mute TTS globally or only for UI-triggered turns?~~
  **Resolved (human decision, task-ui-05):** neither - `Hidden` does not
  touch the voice/TTS pipeline at all in v1. It only changes what the
  Status Console UI itself shows (labels, module chips, screen-preview
  detail). Ordinary voice turns speak normally regardless of Open/Hidden.
- **Deferred:** What is the first authoritative source for module health
  snapshots? The first UI can render `ModuleHealth` snapshots and the manual
  harness can push them, but real health wiring into `main.py` remains a
  future integration task.
- ~~Should reset module actions be available before module lifecycle APIs are
  formalized, or should they start as log-visible requests only?~~
  **Resolved (task-ui-04):** log-visible requests only. No module has a
  reset API yet, so `StatusConsoleApi.reset_module()` always publishes an
  honest `WARN` `SystemEvent` instead of faking success; only the Think
  toggle and the new `ConversationHistory.clear()`-backed global context
  reset have a real engine capability behind them.

## Task Cards

1. done/task-ui-01-state-and-event-contract.md (Completed.)
2. done/task-ui-02-desktop-status-console-shell.md (Completed.)
3. done/task-ui-03-system-events-panel.md (Completed.)
4. done/task-ui-04-think-and-reset-controls.md (Completed.)
5. done/task-ui-05-open-hidden-visibility-mode.md (Completed.)
6. done/task-ui-06-touchstrip-glance-surface.md (Completed.)
7. done/task-ui-07-visual-and-manual-qa.md (Completed.)

## Completion

Completed on 2026-07-07 after task-ui-07's consolidated QA and human manual
review. The first Status Console story now has the desktop shell, system event
panel, Think/reset controls, Open/Hidden visibility mode, touchstrip surface,
and consolidated visual/manual QA in place. Live wiring into `main.py` remains
explicitly outside this story, as recorded in task-ui-03.
