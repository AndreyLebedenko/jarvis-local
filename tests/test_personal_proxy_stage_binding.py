import json
import threading
from dataclasses import replace

import numpy as np
from _backend_fakes import FakeBackend

from jarvis.core.config import PersonalProxySettings
from jarvis.personal_proxy.check.check_result import CheckedTranscript, CheckSource
from jarvis.personal_proxy.common.payload import (
    DEFAULT_SYSTEM_PROMPT,
    build_outbound_payload,
)
from jarvis.personal_proxy.request.stage_binding import StageDependencies, bind_stages
from jarvis.personal_proxy.restoration.restoration_result import RestorationMethod
from jarvis.personal_proxy.sanitize.sanitize_result import (
    SanitizeResult,
    SanitizeVerdict,
)
from jarvis.personal_proxy.stt.speech_guard import NoSpeech, SpeechProbabilities
from jarvis.personal_proxy.stt.stt_result import Transcription

SETTINGS = PersonalProxySettings(stt_min_speech_seconds=0.03)
CLIP = np.full(16000, 0.1, dtype=np.float32)
HEARD = "Позвони Марине"
SANITIZED = "Позвони <PERSON_1>"
MAPPING = {"<PERSON_1>": "Марине"}


class _Engine:
    def __init__(self):
        self.threads = []
        self.clips = []

    def transcribe(self, clip):
        self.threads.append(threading.current_thread())
        self.clips.append(clip)
        return Transcription(HEARD, (), ())


def _probabilities(values):
    return lambda clip: SpeechProbabilities(tuple(values), 0.032)


def _deps(**changes):
    values = {
        "settings": SETTINGS,
        "vad_threshold": 0.5,
        "engine": _Engine(),
        "probabilities": _probabilities([1.0, 1.0]),
        "backend": FakeBackend(),
        "open_stream": lambda payload: _no_stream(),
        "topics_text": "topic line",
        "warm_up": _noop,
    }
    return StageDependencies(**(values | changes))


async def _noop():
    return None


async def _no_stream():
    return
    yield


async def test_transcribe_runs_the_guarded_engine_off_the_event_loop_thread():
    engine = _Engine()
    stages = bind_stages(_deps(engine=engine))

    result = await stages.transcribe(CLIP)

    assert result == Transcription(HEARD, (), ())
    assert engine.threads[0] is not threading.current_thread()


async def test_transcribe_keeps_silence_away_from_the_engine_using_the_vad_threshold():
    engine = _Engine()
    stages = bind_stages(
        _deps(
            engine=engine, probabilities=_probabilities([0.4, 0.4]), vad_threshold=0.5
        )
    )

    result = await stages.transcribe(CLIP)

    assert isinstance(result, NoSpeech)
    assert engine.clips == []


async def test_the_minimum_speech_comes_from_the_personal_proxy_settings():
    engine = _Engine()
    settings = replace(SETTINGS, stt_min_speech_seconds=1.0)
    stages = bind_stages(_deps(engine=engine, settings=settings))

    result = await stages.transcribe(CLIP)

    assert isinstance(result, NoSpeech)
    assert result.required_seconds == 1.0


async def test_sanitize_uses_the_topics_text_and_the_shared_backend():
    reply = json.dumps(
        {
            "verdict": "send",
            "reason": "",
            "sanitized_text": SANITIZED,
            "mapping": MAPPING,
        },
        ensure_ascii=False,
    )
    backend = FakeBackend(reply)
    stages = bind_stages(_deps(backend=backend, topics_text="topic line"))

    result = await stages.sanitize(
        CheckedTranscript(HEARD, (), CheckSource.CHECKED, False)
    )

    assert result == SanitizeResult(SanitizeVerdict.SEND, "", SANITIZED, MAPPING)
    assert "topic line" in backend.requests[0].system


async def test_sanitize_gets_the_public_names_text_in_its_system_prompt():
    heard = "Правда ли, что Эйнштейн ошибался"
    reply = json.dumps(
        {"verdict": "send", "reason": "", "sanitized_text": heard, "mapping": {}},
        ensure_ascii=False,
    )
    backend = FakeBackend(reply)
    stages = bind_stages(_deps(backend=backend, public_names_text="Эйнштейн"))

    result = await stages.sanitize(
        CheckedTranscript(heard, (), CheckSource.CHECKED, False)
    )

    assert result.mapping == {}
    assert "Public names:\nЭйнштейн" in backend.requests[0].system
    assert "Public names" not in backend.requests[0].prompt


async def test_no_public_names_text_leaves_the_system_prompt_without_the_section():
    backend = FakeBackend()
    stages = bind_stages(_deps(backend=backend))

    await stages.sanitize(CheckedTranscript(HEARD, (), CheckSource.CHECKED, False))

    assert "Public names" not in backend.requests[0].system


def test_a_kept_name_has_no_mapping_entry_and_the_gate_lets_it_pass():
    from jarvis.personal_proxy.gate.gate_context import GateContext

    stages = bind_stages(_deps())
    payload = build_outbound_payload(
        DEFAULT_SYSTEM_PROMPT, "Правда ли, что Эйнштейн ошибался"
    )

    assert stages.gate(payload, GateContext({}, "")).allowed


def test_the_public_names_text_is_not_shown_by_the_dependencies_repr():
    assert "Эйнштейн" not in repr(_deps(public_names_text="Эйнштейн"))


def test_the_gate_context_and_the_service_have_no_place_for_public_names():
    import inspect

    from jarvis.personal_proxy.gate.gate_context import GateContext
    from jarvis.personal_proxy.service.proxy_service import PersonalProxyService

    assert not [f for f in GateContext.__dataclass_fields__ if "name" in f]
    parameters = inspect.signature(PersonalProxyService.__init__).parameters
    assert not [p for p in parameters if "name" in p]


def test_the_gate_is_the_deterministic_outbound_gate():
    from jarvis.personal_proxy.gate.gate_context import GateContext

    stages = bind_stages(_deps())
    payload = build_outbound_payload(DEFAULT_SYSTEM_PROMPT, "Позвони <PERSON_1>")

    assert stages.gate(payload, GateContext(MAPPING, "")).allowed
    leaking = build_outbound_payload(DEFAULT_SYSTEM_PROMPT, "Позвони Марине")
    assert not stages.gate(leaking, GateContext(MAPPING, "")).allowed


async def test_open_stream_is_the_given_external_stream_opener():
    opened = []

    def open_stream(payload):
        opened.append(payload)
        return _no_stream()

    stages = bind_stages(_deps(open_stream=open_stream))
    payload = build_outbound_payload(DEFAULT_SYSTEM_PROMPT, "x")

    stages.open_stream(payload)

    assert opened == [payload]


async def test_restore_passes_sentences_without_placeholders_unchanged():
    async def deltas():
        yield "Всё готово."

    stages = bind_stages(_deps())

    sentences = [item async for item in stages.restore(deltas(), MAPPING)]

    assert [(s.text, s.method) for s in sentences] == [
        ("Всё готово.", RestorationMethod.PASSTHROUGH)
    ]


async def test_warm_up_is_the_given_warm_up():
    calls = []

    async def warm_up():
        calls.append("warm")

    await bind_stages(_deps(warm_up=warm_up)).warm_up()

    assert calls == ["warm"]


def test_the_repr_of_the_dependencies_hides_the_topics_text():
    assert "topic line" not in repr(_deps(topics_text="topic line"))


async def test_the_spoken_pass_is_bound_to_the_backend_with_the_contract():
    backend = FakeBackend("пересказ")
    stages = bind_stages(_deps(backend=backend, spoken_contract="CONTRACT"))

    await stages.render_spoken("ответ")

    [request] = backend.requests
    assert (request.system, request.prompt) == ("CONTRACT", "ответ")
