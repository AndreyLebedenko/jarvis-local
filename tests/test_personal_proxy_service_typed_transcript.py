from jarvis.personal_proxy.check.check_result import CheckSource
from jarvis.personal_proxy.confirmation.confirmation_policy import should_ask
from jarvis.personal_proxy.request.typed_transcript import typed_checked_transcript


def test_typed_text_is_carried_whole_with_no_doubts():
    checked = typed_checked_transcript("  Привет, мир  ")

    assert checked.text == "  Привет, мир  "
    assert checked.doubts == ()
    assert checked.fallback_reason is None


def test_typed_text_is_marked_as_typed_and_never_asks():
    checked = typed_checked_transcript("hello")

    assert checked.source is CheckSource.TYPED
    assert checked.would_ask is False
    assert should_ask(checked) is False
