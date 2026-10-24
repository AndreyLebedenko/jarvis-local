"""The texts of the check requests, as the v2.1.0 spikes measured them."""

from __future__ import annotations

from typing import Any

ERROR_HINT = (
    "The engine is reliable on ordinary words but tends to make these mistakes: "
    "e-mail addresses, logins, and web addresses spoken letter by letter come out "
    "glued into one word or mangled; digits in phone, card, account, and passport "
    "numbers are dropped, merged, or changed; names of people and organizations, "
    "especially foreign ones, are respelled or changed, including Latin names "
    "written in Cyrillic; on silence or noise it may invent a phrase."
)
RULES = (
    "Fix only what is evidently wrong. Do not add, remove, paraphrase, translate, "
    "or interpret anything. Output only the corrected transcript, nothing else. "
    "If there is no speech, output nothing."
)

JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "uncertain_fragments": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": ["uncertain_fragments", "confidence"],
}


def sample_prompt(marked_transcript: str) -> str:
    return (
        "A speech-to-text engine produced the transcript below from the attached "
        "recording. Words followed by [?] were low-confidence for the engine: "
        "check them especially, but do not assume they are wrong. Listen to the "
        "recording and check the transcript against it. Do not output the [?] "
        f"marks.\n\n{ERROR_HINT}\n\n{RULES}\n\nTranscript:\n{marked_transcript}"
    )


def judge_prompt(whisper_text: str, candidate_text: str) -> str:
    return (
        "Listen to the attached recording. Transcript A comes from a "
        "speech-to-text engine; transcript B is a corrected version of it. "
        "List the fragments of B (quote them exactly) that you are not sure "
        "match what was said, especially numbers, addresses, and names. Then "
        "give one overall confidence between 0.0 and 1.0 that B is a correct and "
        "complete transcript of the speech: 0.0 means a critical failure, 1.0 "
        "means full confidence. Answer as JSON with the fields "
        '"uncertain_fragments" and "confidence".'
        f"\n\nA:\n{whisper_text}\n\nB:\n{candidate_text}"
    )
