# Story: HotkeyProvider migration for privacy-first global shortcuts

**Статус:** Backlog
**Родитель:** activation / privacy roadmap
**Связано с:** story-voice-trigger-warmup.md, task-03-ptt-hotkey-provider.md
**Дата создания:** 2026-07-06

## Контекст

Jarvis сейчас использует Python package `keyboard` для global hotkeys. Это
практично и уже покрыто тестами через injectable fake modules, но с точки
зрения privacy-first UI/позиционирования у механизма есть слабое место:
`keyboard` работает как global key hook и видит поток нажатий шире, чем нужно
Jarvis.

Для Push-to-Talk в story voice-trigger/warmup предложен Windows
`RegisterHotKey`, который регистрирует конкретную комбинацию и не требует
keystroke sniffing. Это правильное направление, но нельзя надолго оставить
систему в состоянии, где PTT использует один privacy model, а capture,
clipboard, mic sleep, thinking toggle и shutdown продолжают жить на другом.

## Цель

Ввести единый `HotkeyProvider` abstraction и поэтапно перевести все текущие
global hotkeys Jarvis на него, начиная с Windows implementation через
`RegisterHotKey`.

## Границы

- Windows implementation входит в первую фазу.
- Linux/X11/Wayland implementation не входит в первую фазу. Интерфейс должен
  оставлять место для будущего provider, но не обещать поддержку там, где OS
  policy блокирует global shortcuts для обычного приложения.
- Реальная проверка global behavior на машине Андрея остается manual handoff.

## Acceptance Criteria

- [ ] Есть интерфейс `HotkeyProvider`, не содержащий Windows-specific деталей.
- [ ] `WindowsHotkeyProvider` регистрирует конкретные combinations через
      `RegisterHotKey` и сообщает понятную ошибку при конфликте.
- [ ] Все существующие hotkeys проходят через один provider path:
      screenshot full, screenshot region, clipboard submit, mic sleep toggle,
      thinking toggle, shutdown, будущий PTT.
- [ ] Старый `keyboard` dependency удален или явно оставлен только как fallback
      с documented privacy trade-off.
- [ ] Существующие race-avoidance rules сохраняются: callback thread не решает
      состояние сам, а только schedules action на event loop.

## Open Questions

- Нужен ли временный compatibility fallback на `keyboard`, если
  `RegisterHotKey` недоступен или комбинация занята?
- Должен ли UI показывать provider status: `Global hotkeys: native` /
  `fallback` / `unavailable`?
- Нужно ли менять дефолтные hotkeys, если Windows reserved combinations
  конфликтуют чаще, чем текущие `keyboard` bindings?

