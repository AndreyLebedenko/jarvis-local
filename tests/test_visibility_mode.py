from bus import EventBus
from ui_contract import VisibilityMode
from visibility_mode import VisibilityModeChanged, VisibilityModeState


def test_state_starts_open_by_default():
    state = VisibilityModeState(bus=EventBus())

    assert state.mode is VisibilityMode.OPEN


async def test_set_mode_changes_state_and_publishes():
    bus = EventBus()
    received: list[VisibilityModeChanged] = []

    async def on_event(event: VisibilityModeChanged) -> None:
        received.append(event)

    bus.subscribe(VisibilityModeChanged, on_event)
    state = VisibilityModeState(bus=bus)

    await state.set_mode(VisibilityMode.HIDDEN)

    assert state.mode is VisibilityMode.HIDDEN
    assert received == [VisibilityModeChanged(mode=VisibilityMode.HIDDEN)]


async def test_set_mode_to_the_current_mode_is_a_no_op():
    bus = EventBus()
    received: list[VisibilityModeChanged] = []

    async def on_event(event: VisibilityModeChanged) -> None:
        received.append(event)

    bus.subscribe(VisibilityModeChanged, on_event)
    state = VisibilityModeState(bus=bus)

    await state.set_mode(VisibilityMode.OPEN)  # already OPEN

    assert received == []


async def test_set_mode_back_and_forth_publishes_each_real_change():
    bus = EventBus()
    received: list[VisibilityModeChanged] = []

    async def on_event(event: VisibilityModeChanged) -> None:
        received.append(event)

    bus.subscribe(VisibilityModeChanged, on_event)
    state = VisibilityModeState(bus=bus)

    await state.set_mode(VisibilityMode.HIDDEN)
    await state.set_mode(VisibilityMode.HIDDEN)  # redundant, no-op
    await state.set_mode(VisibilityMode.OPEN)

    assert [event.mode for event in received] == [VisibilityMode.HIDDEN, VisibilityMode.OPEN]
