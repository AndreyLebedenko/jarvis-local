"""Prepare a new Jarvis home and run the existing installer there."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, nullcontext
from enum import StrEnum
from pathlib import Path

from jarvis.core.single_instance import (
    MUTEX_NAME,
    AlreadyRunning,
    acquire_single_instance,
)
from tools.deployment_plan import (
    DeploymentMode,
    DeploymentPlan,
    DeploymentPlanError,
    application_inventory,
    plan_deployment,
)
from tools.deployment_snapshot import copy_snapshot, validate_copy

MANIFEST = ".jarvis-deployment.json"
_BOOTSTRAP = Path("tools/install/bootstrap.ps1")
_SCHEMA_VERSION = 1

Installer = Callable[[Path, bool], int]


class DeploymentError(RuntimeError):
    """Deployment could not proceed in the requested directory."""


class _Phase(StrEnum):
    PREPARING = "preparing"
    READY = "ready"
    COMPLETE = "complete"


def _manifest_data(
    target: Path, mode: DeploymentMode, phase: _Phase
) -> dict[str, int | str]:
    return {
        "schema": _SCHEMA_VERSION,
        "target": str(target),
        "mode": mode.value,
        "phase": phase.value,
    }


def _record_phase(target: Path, mode: DeploymentMode, phase: _Phase) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target, prefix=MANIFEST, delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(_manifest_data(target, mode, phase), stream, indent=2)
            stream.write("\n")
        temporary.replace(target / MANIFEST)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _require_resumable(target: Path, mode: DeploymentMode) -> None:
    manifest = target / MANIFEST
    try:
        if manifest.resolve() != manifest:
            raise ValueError("linked deployment manifest")
        payload: object = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, RuntimeError, ValueError) as error:
        raise DeploymentError(
            f"Cannot read deployment manifest {manifest}: {error}"
        ) from error
    if payload == _manifest_data(target, mode, _Phase.PREPARING):
        raise DeploymentError(
            f"Deployment file preparation is incomplete: {target}. "
            "Remove the incomplete directory and start again without -Resume, "
            "or choose a new destination."
        )
    if payload == _manifest_data(target, mode, _Phase.COMPLETE):
        raise DeploymentError(f"Deployment is already complete: {target}")
    if payload != _manifest_data(target, mode, _Phase.READY):
        raise DeploymentError(
            f"Deployment manifest does not match the target or mode: {manifest}"
        )
    application_inventory(target)
    for name in (".venv", "config.toml", "config.ui.toml"):
        path = target / name
        if path.resolve() != path:
            raise DeploymentError(f"Cannot resume with a linked installer path: {path}")
    if mode is DeploymentMode.COPY:
        validate_copy(target, check_snapshot_tree=True)


@contextmanager
def _reserve_deployment(target: Path) -> Iterator[None]:
    identifier = hashlib.sha256(
        os.path.normcase(str(target)).encode("utf-8")
    ).hexdigest()
    guard = acquire_single_instance(name=f"Local\\Jarvis.Deployment.{identifier}")
    if isinstance(guard, AlreadyRunning):
        raise DeploymentError(f"Deployment is already running for {target}")
    try:
        yield
    finally:
        guard.release()


def _prepare(plan: DeploymentPlan) -> None:
    plan.target.mkdir(parents=True)
    _record_phase(plan.target, plan.mode, _Phase.PREPARING)
    print(f"Preparing application files in {plan.target}", flush=True)
    for relative in plan.application_files:
        destination = plan.target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(plan.source / relative, destination)
    if plan.snapshot is not None:
        print(f"Copying the Jarvis snapshot into {plan.target}", flush=True)
        copy_snapshot(plan.source, plan.target, plan.snapshot)
    _record_phase(plan.target, plan.mode, _Phase.READY)


@contextmanager
def _pause_runtime_for_copy() -> Iterator[None]:
    guard = acquire_single_instance(name=MUTEX_NAME)
    if isinstance(guard, AlreadyRunning):
        raise DeploymentError(
            "Close the running Jarvis before copying its installation."
        )
    try:
        yield
    finally:
        guard.release()


def _run_installer(target: Path, assume_yes: bool) -> int:
    arguments = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(target / _BOOTSTRAP),
    ]
    if assume_yes:
        arguments.append("-Yes")
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    return subprocess.run(arguments, cwd=target, env=env, check=False).returncode


def deploy(
    source: Path,
    requested_target: Path,
    *,
    mode: DeploymentMode = DeploymentMode.CLEAN,
    resume: bool = False,
    assume_yes: bool = False,
    installer: Installer = _run_installer,
) -> int:
    try:
        target = requested_target.resolve()
    except (OSError, RuntimeError) as error:
        raise DeploymentError(
            f"Cannot resolve deployment target: {requested_target}"
        ) from error
    try:
        with _reserve_deployment(target):
            if resume:
                _require_resumable(target, mode)
            else:
                exclusion = (
                    _pause_runtime_for_copy()
                    if mode is DeploymentMode.COPY
                    else nullcontext()
                )
                with exclusion:
                    _prepare(plan_deployment(source, requested_target, mode))
            return _install_prepared(target, mode, assume_yes, installer)
    except OSError as error:
        raise DeploymentError(
            f"Cannot deploy to {requested_target}: {error}"
        ) from error


def _install_prepared(
    target: Path, mode: DeploymentMode, assume_yes: bool, installer: Installer
) -> int:
    print(f"Installing Jarvis in {target}", flush=True)
    exit_code = installer(target, assume_yes)
    if exit_code:
        print(
            f"Installer exited with code {exit_code}. "
            "Use -Resume after addressing the error."
        )
    else:
        _record_phase(target, mode, _Phase.COMPLETE)
    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--mode", type=DeploymentMode, default=DeploymentMode.CLEAN)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    try:
        return deploy(
            args.source,
            args.target,
            mode=args.mode,
            resume=args.resume,
            assume_yes=args.yes,
        )
    except (DeploymentError, DeploymentPlanError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
