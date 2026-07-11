# Task: UI privacy semantics and touchstrip requirements

**Статус:** Completed.
**Родитель:** future Status Console / UI roadmap
**Связано с:** .planning/UI/mock-ups, backlog/activation-warmup.md
**Дата создания:** 2026-07-06

## Summary

Зафиксировать UI requirements, которые появились во время визуального
планирования: узкий touchstrip surface, privacy semantics во всех UI, и
интеграция activation/warmup state.

## Decisions

- Touchstrip - не уменьшенная dashboard. Это glance/control surface:
  состояние, backend locality, system visibility mode, Think toggle, reset с
  удержанием, минимальные module indicators.
- Privacy UI делится на две независимые оси:
  - data locality: локальный backend / внешний provider;
  - system visibility mode: насколько Jarvis проявляет себя наружу.
- Старые labels `Приватно / На людях` не использовать как основную модель:
  они описывают окружение пользователя, а не режим системы. Предпочтительный
  рабочий вариант для следующих мокапов: `Open / Hidden`.
- `Open`: обычная работа, голосовой ответ и screen preview разрешены согласно
  текущей конфигурации.
- `Hidden`: Jarvis минимизирует внешнюю заметность в UI: screen previews
  hidden by default, sensitive snippets not shown on small surfaces. Это не
  меняет data locality и не означает cloud/offline status.
  **Уточнено человеком при реализации task-ui-05:** Hidden влияет только на
  отображение в UI (лейблы, module chips, screen preview) и не трогает
  голосовой pipeline - обычные голосовые ответы звучат как обычно независимо
  от Hidden/Open. Более ранняя формулировка этого файла ("TTS muted/
  text-only") была ранним UI-планированием, а не финальным решением;
  описанное здесь - актуальное состояние v1.
- Цветовая семантика: `Open` использует спокойный cyan/teal как штатный local
  режим; `Hidden` использует приглушенный violet/slate как защитный режим.
  Amber оставить для warning/cloud/warmup-adjacent состояний, чтобы Hidden не
  выглядел как ошибка или отправка данных наружу.
- `WARMING` - runtime state activation/warmup, а не privacy state.

## Acceptance Criteria

- [x] В Status Console и touchstrip используется одна терминология для system
      visibility mode.
- [x] Data locality визуально отделена от visibility mode цветом, текстом и
      расположением.
- [x] `WARMING` визуально не читается как cloud/network warning.
- [x] Touchstrip не показывает плотный event log и не требует чтения мелких
      карточек на узком экране.
- [x] Модель в UI берется из runtime config; mock-up literal names не должны
      противоречить `PROJECT.md`.
