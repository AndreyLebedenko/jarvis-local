# Task 03: Push-to-Talk хоткей — абстракция + реализация под Windows

**Story:** story-voice-trigger-warmup.md
**Роль-исполнитель:** Claude Code
**Приоритет:** средний
**Зависимости:** task-01 (вызов `warm_up_model()` из обработчика хоткея)

## Описание

Ввести интерфейс `HotkeyProvider` с методом регистрации колбэка на
нажатие/отпускание комбинации клавиш, и первую реализацию —
`WindowsHotkeyProvider` через `RegisterHotKey` (WinAPI, `ctypes` или
`pywin32`), а не через keystroke-sniffing библиотеку `keyboard` — последняя
глобально видит все нажатия клавиш, что плохо сочетается с privacy-first
позиционированием проекта.

Важно: это не должно остаться единственным hotkey на новом механизме. Текущие
hotkeys (`capture`, clipboard submit, mic sleep, thinking toggle, shutdown)
пока используют `keyboard`. Долгосрочная цель — общий provider для всех
global hotkeys; эта миграция описана отдельно в
`story-hotkey-provider-migration.md`.

Linux-реализация **не входит** в эту задачу (см. story card, «Вне рамок») —
интерфейс должен быть спроектирован так, чтобы `X11HotkeyProvider` можно было
добавить позже без изменений в вызывающем коде.

## Реализация (набросок)

```python
import ctypes
from ctypes import wintypes
import threading

class WindowsHotkeyProvider:
    WM_HOTKEY = 0x0312

    def __init__(self, modifiers: int, vk_code: int, on_trigger):
        self._on_trigger = on_trigger
        self._thread = threading.Thread(target=self._run, args=(modifiers, vk_code), daemon=True)

    def start(self):
        self._thread.start()

    def _run(self, modifiers: int, vk_code: int):
        user32 = ctypes.windll.user32
        hotkey_id = 1
        if not user32.RegisterHotKey(None, hotkey_id, modifiers, vk_code):
            raise RuntimeError("Не удалось зарегистрировать глобальный хоткей — возможно, занят другим приложением")
        msg = wintypes.MSG()
        try:
            while user32.GetMessageA(ctypes.byref(msg), None, 0, 0):
                if msg.message == self.WM_HOTKEY:
                    self._on_trigger()
        finally:
            user32.UnregisterHotKey(None, hotkey_id)
```

Комбинация клавиш должна быть настраиваемой (конфиг), а не захардкожена —
пользователь может уже использовать выбранную комбинацию в другом софте.

## Критерии приёмки

- [ ] `RegisterHotKey` возвращает понятную ошибку в лог/UI, если комбинация
      уже занята другим приложением, а не тихо ничего не делает.
- [ ] Хоткей работает вне фокуса приложения Jarvis Local (это и есть смысл
      Push-to-Talk).
- [ ] Комбинация клавиш конфигурируема.
- [ ] Интерфейс `HotkeyProvider` не содержит Windows-специфичных деталей —
      реализация полностью инкапсулирована в `WindowsHotkeyProvider`.
- [ ] В story/task явно указано, какие старые `keyboard`-based listeners еще
      не мигрированы, чтобы не потерять privacy debt.

## Stop condition / hardware handoff

Регистрация глобальных хоткеев — классическая hardware/OS-зависимая
поверхность (конфликты с другим ПО, поведение при разных раскладках
клавиатуры, поведение в полноэкранных приложениях/играх). Claude Code
реализует и покрывает базовыми автотестами (что код компилируется и вызывает
колбэк в синтетических условиях), но финальная проверка «хоткей
действительно перехватывается глобально на живой машине с реальной
клавиатурой» — на стороне Андрея. Это явный stop point перед закрытием
задачи.
