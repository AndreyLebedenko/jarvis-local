"""The transcript check stage: a local model compares the engine's transcript
with the recording, a second request lists the fragments it doubts, and the
result is the transcript to carry forward plus those doubts. Every failure
falls back to the engine's text with a typed doubt. Nothing is retried or sent."""

from __future__ import annotations

import numpy as np

from jarvis.core.config import PersonalProxySettings
from jarvis.personal_proxy.check.check_backend import ChatRequest, CheckBackend
from jarvis.personal_proxy.check.check_requests import (
    build_judge_request,
    build_sample_request,
)
from jarvis.personal_proxy.check.check_result import (
    CheckedTranscript,
    CheckSource,
    Doubt,
    DoubtKind,
    FallbackReason,
)
from jarvis.personal_proxy.check.judge_parsing import parse_judge
from jarvis.personal_proxy.check.rewrite_guard import detect_rewrite
from jarvis.personal_proxy.check.weak_word_marks import (
    mark_weak_words,
    strip_weak_word_marks,
)
from jarvis.personal_proxy.stt.clip_audio import clip_to_wav_base64
from jarvis.personal_proxy.stt.clip_check import require_valid_clip
from jarvis.personal_proxy.stt.stt_result import Transcription

MAX_FRAGMENT_DOUBTS = 10

_DOUBT_FOR_FALLBACK = {
    FallbackReason.CALL_FAILED: DoubtKind.CHECK_FAILED,
    FallbackReason.EMPTY_SAMPLE: DoubtKind.CHECK_FAILED,
    FallbackReason.UNPARSEABLE_JUDGE: DoubtKind.CHECK_FAILED,
    FallbackReason.INVENTED_ADDRESS: DoubtKind.REWRITE,
    FallbackReason.ALPHABET_SWITCH: DoubtKind.REWRITE,
}


async def check_transcript(
    transcription: Transcription,
    clip: np.ndarray,
    backend: CheckBackend,
    settings: PersonalProxySettings,
) -> CheckedTranscript:
    require_valid_clip(clip)
    whisper_text = transcription.text
    if not whisper_text.strip():
        return _fallback(whisper_text, FallbackReason.EMPTY_TRANSCRIPT)
    audio = clip_to_wav_base64(clip)
    marked = mark_weak_words(transcription.words, settings.stt_weak_word_probability)

    sample = await _reply(
        backend,
        build_sample_request(marked or whisper_text, audio, settings.check_temperature),
    )
    if sample is None:
        return _fallback(whisper_text, FallbackReason.CALL_FAILED)
    candidate = strip_weak_word_marks(sample).strip()
    if not candidate:
        return _fallback(whisper_text, FallbackReason.EMPTY_SAMPLE)
    rewrite = detect_rewrite(whisper_text, candidate)
    if rewrite is not None:
        return _fallback(whisper_text, rewrite)

    answer = await _reply(backend, build_judge_request(whisper_text, candidate, audio))
    if answer is None:
        return _fallback(whisper_text, FallbackReason.CALL_FAILED)
    judged = parse_judge(answer)
    if judged is None:
        return _fallback(whisper_text, FallbackReason.UNPARSEABLE_JUDGE)
    doubts = _fragment_doubts(judged.fragments)
    return CheckedTranscript(
        text=candidate,
        doubts=doubts,
        source=CheckSource.CHECKED,
        would_ask=len(doubts) >= settings.doubt_min_listed,
    )


def _fragment_doubts(fragments: tuple[str, ...]) -> tuple[Doubt, ...]:
    seen: set[str] = set()
    doubts: list[Doubt] = []
    for fragment in fragments:
        key = fragment.strip()
        if key and key not in seen:
            seen.add(key)
            doubts.append(Doubt(DoubtKind.FRAGMENT, fragment))
    return tuple(doubts[:MAX_FRAGMENT_DOUBTS])


async def _reply(backend: CheckBackend, request: ChatRequest) -> str | None:
    try:
        reply = await backend.complete(request)
    except Exception:
        return None
    return reply if isinstance(reply, str) else None


def _fallback(whisper_text: str, reason: FallbackReason) -> CheckedTranscript:
    kind = _DOUBT_FOR_FALLBACK.get(reason)
    doubts = (Doubt(kind),) if kind is not None else ()
    return CheckedTranscript(
        text=whisper_text,
        doubts=doubts,
        source=CheckSource.WHISPER_FALLBACK,
        would_ask=reason is not FallbackReason.EMPTY_TRANSCRIPT,
        fallback_reason=reason,
    )
