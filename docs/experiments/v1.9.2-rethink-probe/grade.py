"""Mechanical checks for the predeclared formal constraints, plus a
draft-vs-final comparison. Aesthetic judgement stays with the human."""

import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"
BANNED_C04 = ("блокнот", "записн", "шпаргалк", "черновик", "памяти человека")


def sentences(t):
    return [s for s in re.split(r"(?<=[.!?…])\s+", t.strip()) if s.strip()]


def lines(t):
    return [ln for ln in t.strip().splitlines() if ln.strip()]


def has_markdown(t):
    return bool(re.search(r"\*\*|^\s*[*#]|^\s*\d+\.\s|`", t, re.M))


CHECKS = {
    "p03": lambda t: {
        "sentences==3": len(sentences(t)) == 3,
        "no_pamyat": "памят" not in t.lower(),
        "no_markdown": not has_markdown(t),
    },
    "c01": lambda t: {
        "lines==3": len(lines(t)) == 3,
        "no_extra_prose": len(lines(t)) <= 3,
    },
    "c02": lambda t: {"lines==8": len(lines(t)) == 8},
    "c03": lambda t: {"sentences==3": len(sentences(t)) == 3},
    "c04": lambda t: {
        "sentences==1": len(sentences(t)) == 1,
        "no_banned": not any(b in t.lower() for b in BANNED_C04),
    },
}


def split_critique(raw):
    verdict = re.search(r"VERDICT:\s*(.*)", raw)
    answer = re.search(r"ANSWER:\s*(.*)", raw, re.S)
    return (
        verdict.group(1).strip() if verdict else "<no VERDICT>",
        (answer.group(1) if answer else raw).strip(),
    )


def load(case, tag):
    p = OUT / f"{case}-{tag}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def main():
    draft_tag, crit_tags = sys.argv[1], sys.argv[2:]
    ids = [f"p{i:02d}" for i in range(1, 11)] + ["c01", "c02", "c03", "c04"]
    for case in ids:
        d = load(case, draft_tag)
        if d is None:
            continue
        print("=" * 74)
        print(f"{case}  draft[{draft_tag}] {d['wall_seconds']}s "
              f"eval={d['eval_count']} out={len(d['text'])}ch")
        if case in CHECKS:
            print(f"   draft form: {CHECKS[case](d['text'])}")
        for tag in crit_tags:
            c = load(case, tag)
            if c is None:
                continue
            verdict, answer = split_critique(c["text"])
            same = answer == d["text"].strip()
            print(f"   [{tag}] {c['wall_seconds']}s eval={c['eval_count']} "
                  f"identical={same} dlen={len(answer) - len(d['text']):+d}")
            print(f"      VERDICT: {verdict[:180]}")
            if case in CHECKS and not same:
                print(f"      final form: {CHECKS[case](answer)}")


if __name__ == "__main__":
    main()
