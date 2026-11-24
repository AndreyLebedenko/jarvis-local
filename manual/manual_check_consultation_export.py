"""Isolated consultation PoC: freeze, prepare, score, then reviewed application."""

import argparse
from collections.abc import Sequence
from pathlib import Path

from manual.consultation_export.runner import (
    freeze,
    run_application,
    run_preparation,
    score_preparation,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "prepare", "score", "apply"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    commands = {
        "freeze": freeze,
        "prepare": run_preparation,
        "score": score_preparation,
        "apply": run_application,
    }
    commands[args.command](args.out.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
