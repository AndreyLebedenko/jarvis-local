"""Helpers that run the wizard's PowerShell modules without opening a window."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

WIZARD_DIR = Path(__file__).resolve().parents[1] / "tools" / "install"


def run_powershell(
    script: Path,
    *args: Path | str,
    env: dict[str, str] | None = None,
    sta: bool = False,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    """Windows PowerShell 5.1, the host the wizard itself uses. Values with
    quotes travel in `env`, because a native argument loses embedded quotes."""
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            *(["-STA"] if sta else []),
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            *(str(arg) for arg in args),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=timeout,
        env={**os.environ, **(env or {})},
    )


def run_snippet(
    tmp_path: Path,
    body: str,
    *modules: str,
    env: dict[str, str] | None = None,
    sta: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Dot-sources the named wizard modules, then runs `body`. The script file
    is UTF-8 with a BOM so that Windows PowerShell 5.1 reads non-ASCII literals."""
    sources = "".join(f". '{WIZARD_DIR / module}'\n" for module in modules)
    script = tmp_path / "snippet.ps1"
    script.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)\n"
        + sources
        + body,
        encoding="utf-8-sig",
    )
    return run_powershell(script, env=env, sta=sta)


def report(**entries: str) -> str:
    """PowerShell that prints one compact JSON object of the given expressions,
    one entry per line so that long snippets stay readable."""
    lines = "".join(f"    {key} = ({expr})\n" for key, expr in entries.items())
    return "[ordered]@{\n" + lines + "} | ConvertTo-Json -Compress -Depth 8\n"


def json_lines(result: subprocess.CompletedProcess[str]) -> list:
    assert result.returncode == 0, result.stdout + result.stderr
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
