from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = PROJECT_ROOT / "docs" / "architecture"
DEFAULT_OUTPUT = DEFAULT_SOURCE / "rendered"


@dataclass(frozen=True)
class Distribution:
    version: str
    url: str
    sha256: str
    jar_path: Path


PLANTUML = Distribution(
    version="1.2026.6",
    url=(
        "https://github.com/plantuml/plantuml/releases/download/"
        "v1.2026.6/plantuml-1.2026.6.jar"
    ),
    sha256="89948f14c93756c7a3fb7b69078ff37e8489fd79dd430c582b931e2f65358690",
    jar_path=PROJECT_ROOT / ".tools" / "plantuml" / "plantuml-1.2026.6.jar",
)


class PlantUmlToolError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _verify(path: Path, expected_sha256: str) -> None:
    actual_sha256 = _sha256(path)
    if actual_sha256 != expected_sha256:
        raise PlantUmlToolError(
            f"PlantUML JAR SHA-256 mismatch: expected {expected_sha256}, "
            f"got {actual_sha256}"
        )


def install(distribution: Distribution = PLANTUML) -> Path:
    destination = distribution.jar_path
    if destination.exists():
        _verify(destination, distribution.sha256)
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".download")
    try:
        with (
            urlopen(distribution.url, timeout=120) as response,
            temporary.open("wb") as output,
        ):
            shutil.copyfileobj(response, output)
        _verify(temporary, distribution.sha256)
        temporary.replace(destination)
    except (OSError, PlantUmlToolError) as error:
        temporary.unlink(missing_ok=True)
        if isinstance(error, PlantUmlToolError):
            raise
        raise PlantUmlToolError(f"PlantUML download failed: {error}") from error
    return destination


def require_jar(distribution: Distribution = PLANTUML) -> Path:
    if not distribution.jar_path.exists():
        raise PlantUmlToolError(
            "PlantUML JAR is not installed. Run: python tools/plantuml.py install"
        )
    _verify(distribution.jar_path, distribution.sha256)
    return distribution.jar_path


def _java_command(arguments: Sequence[str]) -> list[str]:
    java_path = shutil.which("java")
    if java_path is None:
        raise PlantUmlToolError(
            "Java is unavailable. Configure Java 17 or newer before running PlantUML."
        )
    if Path(java_path).suffix.lower() not in {".bat", ".cmd"}:
        return [java_path, *arguments]

    command_interpreter = os.environ.get("COMSPEC")
    if not command_interpreter:
        raise PlantUmlToolError("Windows command interpreter is unavailable.")
    batch_command = subprocess.list2cmdline([java_path, *arguments])
    return [command_interpreter, "/d", "/s", "/c", batch_command]


def _run(arguments: Sequence[str]) -> int:
    command = _java_command(arguments)
    try:
        result = subprocess.run(command, check=False)
    except FileNotFoundError as error:
        raise PlantUmlToolError(
            f"Java launcher could not start: {command[0]}"
        ) from error
    return result.returncode


def check_syntax(sources: Sequence[Path], distribution: Distribution = PLANTUML) -> int:
    jar_path = require_jar(distribution)
    command = [
        "-jar",
        str(jar_path),
        "-stdrpt:1",
        "--check-syntax",
        *(str(source) for source in sources),
    ]
    return _run(command)


def render(
    sources: Sequence[Path],
    output_dir: Path,
    output_format: str,
    distribution: Distribution = PLANTUML,
) -> int:
    jar_path = require_jar(distribution)
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        "-jar",
        str(jar_path),
        "--format",
        output_format,
        "--output-dir",
        str(output_dir.resolve()),
        *(str(source) for source in sources),
    ]
    return _run(command)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install, verify, and render the project's PlantUML diagrams."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "install", help="Download and verify the pinned PlantUML JAR."
    )

    check_parser = subparsers.add_parser(
        "check", help="Validate PlantUML syntax without rendering."
    )
    check_parser.add_argument("sources", nargs="*", type=Path)

    render_parser = subparsers.add_parser(
        "render", help="Validate and render PlantUML diagrams."
    )
    render_parser.add_argument("sources", nargs="*", type=Path)
    render_parser.add_argument(
        "--format", choices=("svg", "png"), default="svg", dest="output_format"
    )
    render_parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT, dest="output_dir"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "install":
            path = install()
            print(f"PlantUML {PLANTUML.version} installed at {path}")
            return 0

        sources = tuple(arguments.sources) or (DEFAULT_SOURCE,)
        if arguments.command == "check":
            return check_syntax(sources)
        return render(sources, arguments.output_dir, arguments.output_format)
    except PlantUmlToolError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
