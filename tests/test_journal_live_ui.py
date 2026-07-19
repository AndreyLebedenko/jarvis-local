"""task-journal-06: structural checks for the live feed and audio playback.

Same approach as tests/test_journal_view_ui.py: parse the UI sources as
text and assert structure, never run a browser (Testing protocol - live
end-to-end and audible playback are the human-run handoff).
"""

import re

from jarvis.ui.status_console import UI_DIR

APP_JS = (UI_DIR / "app.js").read_text(encoding="utf-8")
STYLE_CSS = (UI_DIR / "style.css").read_text(encoding="utf-8")
STRINGS_JS = (UI_DIR / "strings.js").read_text(encoding="utf-8")


def _function_body(name, prefix="function "):
    return APP_JS.split(f"{prefix}{name}(")[1].split("\n}")[0]


def test_journal_event_delta_is_dispatched_to_apply_journal_event():
    dispatch_table = APP_JS.split("function _applyStateDelta(")[1].split("\n}")[0]
    assert "journal_event: applyJournalEvent," in dispatch_table


def test_journal_event_appends_only_to_the_displayed_session():
    """The session list metadata always refreshes, but the feed only grows
    when the event belongs to the session currently on screen - viewing an
    old session must not jump."""
    body = _function_body("applyJournalEvent")
    assert "refreshJournalSessions();" in body
    guard = "if (payload.session_id !== _journalSelectedSessionId) return;"
    append = "_appendJournalTurn(payload);"
    assert guard in body
    assert append in body
    assert (
        body.index("refreshJournalSessions();") < body.index(guard) < body.index(append)
    )


def test_dock_input_event_selects_its_new_session():
    submit_body = _function_body("submitJournalInput", prefix="async function ")
    assert "_journalSelectPendingInputSession = true;" in submit_body
    assert submit_body.index("_journalSelectPendingInputSession = true;") < (
        submit_body.index("await fetch")
    )

    apply_body = _function_body("applyJournalEvent")
    select_call = "selectJournalSession(payload.session_id);"
    guard = "if (payload.session_id !== _journalSelectedSessionId) return;"
    assert "if (_shouldSelectJournalInputSession(payload)) {" in apply_body
    assert select_call in apply_body
    assert apply_body.index(select_call) < apply_body.index(guard)

    helper = _function_body("_shouldSelectJournalInputSession")
    assert "_journalSelectPendingInputSession" in helper
    assert 'payload.role === "user"' in helper
    assert 'payload.source === "dock"' in helper


def test_journal_event_is_ignored_while_hidden_or_off_view():
    body = _function_body("applyJournalEvent")
    assert "if (_isHiddenActive()) return;" in body
    assert "if (!_isJournalActive()) return;" in body


def test_append_keeps_bottom_anchor_only_when_pinned():
    """Pinned-to-bottom stays pinned as turns append; a user who scrolled
    up keeps their position (scrollTop is only touched behind the pinned
    check, which is computed before the append)."""
    body = _function_body("_appendJournalTurn")
    assert "feed.scrollHeight - feed.scrollTop - feed.clientHeight <= 40" in body
    assert "if (pinned) feed.scrollTop = feed.scrollHeight;" in body
    assert body.index("const pinned") < body.index("feed.appendChild")


def test_append_does_not_rerender_existing_turns():
    """Playing state must survive appends: the live path adds one element
    and never rebuilds the feed."""
    body = _function_body("_appendJournalTurn")
    assert "appendChild" in body
    assert "replaceChildren" not in body


def test_single_playback_invariant():
    """Starting one tile stops the previously active one before play()."""
    body = _function_body("_toggleJournalPlayback")
    assert "_stopJournalPlayback();" in body
    assert body.index("_stopJournalPlayback();") < body.index("audio.play()")
    stop_body = _function_body("_stopJournalPlayback")
    assert "_journalActiveAudio.pause();" in stop_body
    assert "_journalActiveAudio = null;" in stop_body


def test_hidden_and_feed_rerender_stop_playback():
    """Hidden mid-playback stops audio immediately (via
    _clearJournalContent), and a full feed re-render stops it too - a
    detached <audio> element would keep sounding."""
    assert "_stopJournalPlayback();" in _function_body("_clearJournalContent")
    assert "_stopJournalPlayback();" in _function_body("_renderJournalFeed")


def test_audio_tile_uses_plain_html5_audio_against_the_media_url():
    body = _function_body("_journalAudioTile")
    assert 'document.createElement("audio")' in body
    assert "audio.src = mediaItem.url;" in body
    assert '"file:' not in APP_JS  # no file:// URLs built in code


def test_image_tile_uses_media_url_and_missing_placeholder():
    body = _function_body("_journalImageThumbnail")
    assert "image.src = mediaItem.url;" in body
    assert "journal-image-missing" in body
    assert 'uiString("journal_image_missing")' in body
    assert 'image.addEventListener("error"' in body
    compact = re.sub(r"\s+", " ", STYLE_CSS)
    assert ".journal-image-tile {" in compact


def test_audio_tile_has_play_toggle_progress_and_duration():
    body = _function_body("_journalAudioTile")
    assert "_toggleJournalPlayback(audio)" in body
    assert "journal-audio-play" in body
    assert "journal-audio-progress-fill" in body
    assert "journal-audio-duration" in body
    assert '"timeupdate"' in body
    assert '"loadedmetadata"' in body
    compact = re.sub(r"\s+", " ", STYLE_CSS)
    assert ".journal-audio-play {" in compact
    assert ".journal-audio-progress-fill {" in compact


def test_tile_state_follows_audio_events_not_the_click():
    """Button glyph/playing attribute change only from the element's own
    play/pause events - the click handler never stamps playing state."""
    tile_body = _function_body("_journalAudioTile")
    assert 'audio.addEventListener("play"' in tile_body
    assert 'audio.addEventListener("pause"' in tile_body
    toggle_body = _function_body("_toggleJournalPlayback")
    assert "dataset.playing" not in toggle_body
    assert "textContent" not in toggle_body


def test_natural_end_releases_the_active_audio_and_resets_the_button():
    """review P1: ended must not rely on the browser also emitting pause -
    the shared showPaused updater runs on both, so the next click on the
    same tile replays instead of hitting the still-active pause branch."""
    tile_body = _function_body("_journalAudioTile")
    assert 'audio.addEventListener("pause", showPaused);' in tile_body
    ended_body = tile_body.split('audio.addEventListener("ended"')[1].split("});")[0]
    assert "showPaused();" in ended_body
    show_paused = tile_body.split("const showPaused = () => {")[1].split("};")[0]
    assert (
        "if (_journalActiveAudio === audio) _journalActiveAudio = null;" in show_paused
    )
    assert 'tile.dataset.playing = "false";' in show_paused


def test_assistant_copy_button_copies_recorded_text():
    body = _function_body("_journalEventElement")
    assert 'event.role === "assistant" && event.text' in body
    assert "copyJournalAnswer(event.text, copy)" in body
    copy_body = _function_body("copyJournalAnswer", prefix="async function ")
    assert "navigator.clipboard.writeText" in APP_JS
    assert 'document.execCommand("copy")' in APP_JS
    assert 'uiString("journal_copy_done")' in copy_body


def test_usage_and_delete_controls_are_wired_to_session_list():
    assert '_fetchJournalJson("/api/journal/usage")' in APP_JS
    assert "journalUsageTotal" in APP_JS
    assert "deleteJournalSession(session.id)" in APP_JS
    delete_body = _function_body("deleteJournalSession", prefix="async function ")
    assert "window.confirm(message)" in delete_body
    assert 'method: "DELETE"' in delete_body
    assert "_scheduleJournalSearch();" in delete_body


def test_live_event_during_inflight_feed_fetch_defers_to_a_refetch():
    """review P2: an append racing an in-flight feed fetch would be wiped
    by the older response's _renderJournalFeed(). While a fetch is in
    flight the event sets the refetch flag instead of appending, and the
    fetch that rendered last refetches once."""
    apply_body = _function_body("applyJournalEvent")
    assert "if (_journalFeedFetchesInFlight > 0) {" in apply_body
    deferred = apply_body.split("_journalFeedFetchesInFlight > 0) {")[1].split("}")[0]
    assert "_journalFeedRefetchSessionId = payload.session_id;" in deferred
    assert "return;" in deferred

    select_body = _function_body("selectJournalSession", prefix="async function ")
    assert "_journalFeedFetchesInFlight += 1;" in select_body
    assert "_journalFeedFetchesInFlight -= 1;" in select_body
    # Every completion checks the deferred refetch - stale and
    # generation-invalidated responses included (either can be the last to
    # land, and bailing before the check would strand the deferred live
    # event). So the completion path must not early-return before the
    # check: the validity conditions gate only the render.
    assert "_maybeRefetchJournalFeed();" in select_body
    completion = select_body.split("_journalFeedFetchesInFlight -= 1;")[1]
    before_check = completion.split("_maybeRefetchJournalFeed();")[0]
    assert "return;" not in before_check
    render_guard = "if (valid && _journalSelectedSessionId === sessionId) {"
    assert render_guard in before_check
    assert (
        "generation === _journalContentGeneration && !_isHiddenActive()" in before_check
    )

    maybe_body = _function_body("_maybeRefetchJournalFeed")
    assert "if (_journalFeedFetchesInFlight !== 0) return;" in maybe_body
    assert "if (_isHiddenActive()) return;" in maybe_body
    assert "_journalFeedRefetchSessionId = null;" in maybe_body
    assert "if (sessionId !== _journalSelectedSessionId) return;" in maybe_body
    assert "selectJournalSession(sessionId);" in maybe_body
    # Hidden wipes the deferred session so a stale refetch cannot fire
    # after switching back to Open.
    assert "_journalFeedRefetchSessionId = null;" in _function_body(
        "_clearJournalContent"
    )


def test_playback_strings_exist_in_both_languages():
    for language in ("en", "ru"):
        marker = f"  {language}: {{"
        start = STRINGS_JS.index(marker)
        end = STRINGS_JS.index("\n  },", start)
        body = STRINGS_JS[start:end]
        assert "journal_audio_play:" in body
        assert "journal_audio_pause:" in body
