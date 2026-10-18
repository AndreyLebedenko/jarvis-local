"""Offline rehearsal of the whole spike: runner, scorer, decision, report.

A scripted fake model plays all three arms over a few utterances, so a wiring
mistake between the modules shows up here and not in the owner's live run.
"""

import asyncio
import json

from jarvis.core.config import GenerationOptions
from manual.personal_proxy.corpus import CONTROLS, utterance_by_id
from manual.personal_proxy.decision import Outcome, decide
from manual.personal_proxy.records import (
    Arm,
    CallRecord,
    CallStage,
    load_generations,
)
from manual.personal_proxy.report import render_report
from manual.personal_proxy.runner import ARMS, GenerationRunner, plan_jobs, run_jobs
from manual.personal_proxy.scoring import aggregate, score_records

SUBJECTS = ["id_short_call", "id_phone_words", "n_short_tokyo", "t_diabetes"]
AUDIO = {subject: f"wav:{subject}".encode() for subject in SUBJECTS}
SANITIZED = {
    "id_short_call": ("Позвони <PERSON_1>.", {"<PERSON_1>": "Марина Крылова"}),
    "id_phone_words": ("Запиши мой телефон: <PHONE_1>.", {"<PHONE_1>": "89152345678"}),
    "n_short_tokyo": ("Который час в Токио?", {}),
}


class ScriptedModel:
    """Answers every request the way a well-behaved model would, optionally
    leaking the first name in the combined-system arm."""

    def __init__(self, leak_in_system_arm=False, seconds=None):
        self._leak = leak_in_system_arm
        self._seconds = seconds or {}
        self.by_audio = {v: k for k, v in AUDIO.items()}

    def _subject_of(self, request):
        if request.audio is not None:
            return self.by_audio.get(request.audio)
        if request.stage is CallStage.SANITIZE_TEXT:
            transcript = request.messages[-1]["content"].split("\n", 1)[1]
            return next(
                (s for s in SUBJECTS if utterance_by_id(s).text == transcript), None
            )
        return None

    async def __call__(self, request):
        subject = self._subject_of(request)
        text = self._response(request, subject)
        arm_key = (
            "system"
            if request.messages and request.messages[0]["role"] == "system"
            else "other"
        )
        total = self._seconds.get((request.stage, arm_key), 1.0)
        return CallRecord(request.stage, {}, text, "stop", 5, 5, 0.0, total)

    def _response(self, request, subject):
        if request.stage is CallStage.TRANSCRIBE:
            return utterance_by_id(subject).text if subject else "warm"
        if subject is None:
            return "{}"
        utterance = utterance_by_id(subject)
        if utterance.expected_verdict.value == "refuse":
            document = {"verdict": "refuse", "reason": "medical", "sanitized_text": ""}
        else:
            sanitized, mapping = SANITIZED[subject]
            if (
                self._leak
                and subject == "id_short_call"
                and request.messages[0]["role"] == "system"
                and request.stage is CallStage.COMBINED
            ):
                sanitized = "Позвони Марине."
            document = {
                "verdict": "send",
                "reason": "",
                "sanitized_text": sanitized,
                "mapping": mapping,
            }
        document.setdefault("mapping", {})
        if request.stage is CallStage.COMBINED:
            document["raw_transcript"] = utterance.text
        return json.dumps(document, ensure_ascii=False)


def _run(model, tmp_path):
    runner = GenerationRunner(
        model,
        GenerationOptions(),
        transcribe_instruction="Transcribe it.",
        topics="- t",
        use_format=False,
    )
    jobs = plan_jobs(SUBJECTS, seeds=(1,), arms=ARMS)
    asyncio.run(
        run_jobs(runner, jobs, AUDIO.__getitem__, tmp_path / "calls", warm_audio=None)
    )
    return score_records(load_generations(tmp_path / "calls"), CONTROLS)


def test_a_faithful_model_scores_clean_across_all_three_arms(tmp_path):
    scores = _run(ScriptedModel(), tmp_path)

    for arm in ARMS:
        metrics = aggregate(arm, scores)
        assert metrics.generations == len(SUBJECTS)
        assert metrics.validity == 1.0
        assert metrics.spans_leaked == 0
        assert metrics.audio_failures == 0
        assert metrics.false_refusals == 0
        assert metrics.missed_refusals == 0
        assert metrics.mapping_errors == 0


def test_a_leak_in_one_arm_only_shows_up_in_that_arm(tmp_path):
    scores = _run(ScriptedModel(leak_in_system_arm=True), tmp_path)

    assert aggregate(Arm.C_SYSTEM, scores).spans_leaked == 1
    assert aggregate(Arm.C_USER, scores).spans_leaked == 0
    assert aggregate(Arm.T_PLUS_S, scores).spans_leaked == 0


def test_decision_and_report_render_from_real_run_output(tmp_path):
    seconds = {
        (CallStage.TRANSCRIBE, "other"): 1.5,
        (CallStage.SANITIZE_TEXT, "system"): 2.5,
        (CallStage.COMBINED, "other"): 1.0,
        (CallStage.COMBINED, "system"): 1.0,
    }
    scores = _run(ScriptedModel(seconds=seconds), tmp_path)
    metrics = [aggregate(arm, scores) for arm in ARMS]

    decision = decide(metrics[0], metrics[1:])
    report = render_report(
        meta={"model": "fake"},
        decision=decision,
        metrics=metrics,
        scores=scores,
        duration_of=lambda _: 3.0,
    )

    assert decision.outcome in set(Outcome)
    assert "Outcome:" in report
    assert report.isascii()
    assert "c_user" in report and "c_system" in report
