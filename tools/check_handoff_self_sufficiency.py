"""Check that changed handoff sections stay self-sufficient.

Enforces the handoff self-sufficiency rule (AGENTS.md / CLAUDE.md Testing
protocol item 4) at the git layer, so the guarantee does not depend on
agent discipline: a handoff step that names a hotkey ("press the ...
hotkey"), a config key, or a binding must name its literal value in the
same handoff. Run on changed ``tasks/**`` files (staged files for the
pre-commit hook, or an explicit path list for manual runs).

What it checks (heuristic, deliberately cheap):

- Any handoff-ish file (``handoff`` in name, or a ``handoff`` section
  heading) that mentions "hotkey" or "Ctrl+Alt" / "Cmd+Shift" style
  bindings without a single literal binding token in that file.
- A file whose handoff section says "press" near a hotkey/binding word
  with no literal binding anywhere in the file.

The checker is intentionally conservative: it only flags files that talk
about hotkeys at all, and only when not a single literal binding appears
anywhere in them. It does not try to associate each mention with its
nearest paragraph - that would produce false positives on well-formed
handoffs with several prose mentions and one binding list.

Usage:
    python tools/check_handoff_self_sufficiency.py            # staged files
    python tools/check_handoff_self_sufficiency.py path1 ...  # explicit
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# A literal binding: Ctrl+Alt+O, Cmd+Shift+P, Win+F1 (any modifier group
# followed by a key), as written in README hotkey tables.
BINDING_RE = re.compile(
    r"\b(?:Ctrl|Control|Cmd|Command|Win|Alt|Shift|Meta)"
    r"(?:\s*\+\s*(?:Ctrl|Control|Cmd|Command|Win|Alt|Shift|Meta))+"
    r"\s*\+\s*[^+\s]+",
    re.IGNORECASE,
)

HOTKEY_MENTION_RE = re.compile(r"\bhotkey\b|\bkey ?binding\b", re.IGNORECASE)

# A hotkey-shaped compound with at least one modifier, with or without the
# plus signs (used only to decide a file talks about bindings at all).
BINDING_WORD_RE = re.compile(
    r"\b(?:Ctrl|Control|Cmd|Win|Alt|Shift|Meta)\b", re.IGNORECASE
)

HANDOFF_FILE_RE = re.compile(r"handoff", re.IGNORECASE)

HANDOFF_SECTION_RE = re.compile(
    r"^#{1,6}[^\n]*handoff[^\n]*$", re.IGNORECASE | re.MULTILINE
)

# "press the cycle hotkey", "hotkey press", "pressing the hotkey" - an
# instruction to press something that is referred to but not named.
UNNAMED_PRESS_RE = re.compile(
    r"\bpress(?:ing|es)?\b[^.\n]*\b(?:the\s+)?(?:cycle\s+|cycling\s+|"
    r"response[- ]mode\s+|toggle\s+)?hotkey\b",
    re.IGNORECASE,
)


def staged_task_md_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return [
        name
        for name in result.stdout.splitlines()
        if name.startswith("tasks/") and name.endswith(".md")
    ]


def handoff_span(text: str) -> tuple[int, int] | None:
    """Return (start, end) of the first handoff section, or None."""
    match = HANDOFF_SECTION_RE.search(text)
    if match is None:
        return None
    next_heading = HANDOFF_SECTION_RE.search(text, match.end())
    end = next_heading.start() if next_heading else len(text)
    return (match.start(), end)


def handoffish(path: Path, text: str) -> bool:
    if HANDOFF_FILE_RE.search(path.name):
        return True
    return handoff_span(text) is not None


def check_file(repo_relative: str) -> list[str]:
    path = REPO_ROOT / repo_relative
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    if not handoffish(path, text):
        return []
    if not (HOTKEY_MENTION_RE.search(text) or UNNAMED_PRESS_RE.search(text)):
        return []
    if BINDING_RE.search(text):
        return []
    problems = []
    if UNNAMED_PRESS_RE.search(text):
        problems.append(
            f"{repo_relative}: handoff instructs pressing a hotkey "
            '("press ... hotkey") without naming the literal binding '
            "(e.g. Ctrl+Alt+O). Testing protocol item 4: every hotkey is "
            "named literally with a source reference."
        )
    span = handoff_span(text)
    if span is not None:
        section_text = text[span[0] : span[1]]
        if (
            HOTKEY_MENTION_RE.search(section_text)
            and not BINDING_RE.search(section_text)
            and BINDING_WORD_RE.search(section_text)
            and not problems
        ):
            problems.append(
                f"{repo_relative}: handoff section mentions hotkeys but "
                "states no literal binding (e.g. Ctrl+Alt+O). Testing "
                "protocol item 4: every hotkey is named literally with a "
                "source reference."
            )
    if not problems:
        problems.append(
            f"{repo_relative}: handoff mentions hotkeys but contains no "
            "literal binding (e.g. Ctrl+Alt+O). Testing protocol item 4: "
            "every hotkey is named literally with a source reference."
        )
    return problems


def main(argv: list[str]) -> int:
    files = argv[1:] if len(argv) > 1 else staged_task_md_files()
    if not files:
        return 0
    problems: list[str] = []
    for name in files:
        problems.extend(check_file(name))
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(
            f"handoff self-sufficiency check: {len(problems)} problem(s)",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
