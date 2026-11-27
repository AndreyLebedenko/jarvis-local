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

from jarvis.core.brand_icon import BrandIconError
from jarvis.core.brand_render import Renderer, run_powershell_renderer
from jarvis.core.config import ConfigError
from jarvis.core.single_instance import (
    MUTEX_NAME,
    AlreadyRunning,
    acquire_single_instance,
)
from tools.deployment_brand import (
    BRAND_ENVIRONMENT_VARIABLE,
    BrandPlan,
    BrandRequest,
    BrandStageError,
    apply_brand,
    generate_missing_icons,
    plan_brand,
    request_from_environment,
)
from tools.deployment_brand_check import BRAND_CHECK_PREFIX, check_brand_environment
from tools.deployment_plan import (
    DeploymentMode,
    DeploymentPlan,
    DeploymentPlanError,
    application_inventory,
    plan_deployment,
)
from tools.deployment_rebrand import REBRAND_PREFIX, check_home_brand, rebrand_home
from tools.deployment_shortcut import shortcut_result
from tools.deployment_snapshot import copy_snapshot, snapshot_layers, validate_copy

MANIFEST = ".jarvis-deployment.json"
PREVIEW_PREFIX = "JARVIS_DEPLOY_PREVIEW:"
RESULT_PREFIX = "JARVIS_DEPLOY_RESULT:"
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


def _prepare(plan: DeploymentPlan, brand: BrandPlan) -> None:
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
    apply_brand(brand, plan.target)
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
    if env.pop("JARVIS_DEPLOY_NONINTERACTIVE", None) == "1":
        arguments.insert(2, "-NonInteractive")
        env["PYTHONUNBUFFERED"] = "1"
    env.pop("PYTHONPATH", None)
    env.pop(BRAND_ENVIRONMENT_VARIABLE, None)
    return subprocess.run(arguments, cwd=target, env=env, check=False).returncode


def deploy(
    source: Path,
    requested_target: Path,
    *,
    mode: DeploymentMode = DeploymentMode.CLEAN,
    resume: bool = False,
    assume_yes: bool = False,
    installer: Installer = _run_installer,
    brand: BrandRequest | None = None,
    renderer: Renderer = run_powershell_renderer,
) -> int:
    _reject_brand_on_resume(resume, brand)
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
                    plan = plan_deployment(source, requested_target, mode)
                    _prepare(plan, plan_brand(plan.source, mode, brand))
            return _install_prepared(target, mode, assume_yes, installer, renderer)
    except OSError as error:
        raise DeploymentError(
            f"Cannot deploy to {requested_target}: {error}"
        ) from error


def _reject_brand_on_resume(resume: bool, brand: BrandRequest | None) -> None:
    if resume and brand is not None and not brand.is_empty:
        raise DeploymentError(
            "The brand was prepared with the files and cannot be changed while "
            "resuming. Start a new deployment to change it."
        )


def _generate_icons(target: Path, renderer: Renderer) -> bool:
    try:
        message = generate_missing_icons(target, renderer=renderer)
    except (BrandStageError, BrandIconError, ConfigError, OSError) as error:
        print(f"[failed] Generate brand icons: {error}")
        print("Use -Resume after addressing the error.")
        return False
    if message:
        print(message, flush=True)
    return True


def _install_prepared(
    target: Path,
    mode: DeploymentMode,
    assume_yes: bool,
    installer: Installer,
    renderer: Renderer,
) -> int:
    if not _generate_icons(target, renderer):
        return 1
    print(f"Installing Jarvis in {target}", flush=True)
    exit_code = installer(target, assume_yes)
    if exit_code:
        print(
            f"Installer exited with code {exit_code}. "
            "Use -Resume after addressing the error."
        )
    else:
        _record_phase(target, mode, _Phase.COMPLETE)
        print(RESULT_PREFIX + json.dumps(shortcut_result(target)), flush=True)
    return exit_code


def preview_deployment(
    source: Path,
    target: Path,
    mode: DeploymentMode,
    *,
    resume: bool,
    brand: BrandRequest | None = None,
) -> dict[str, object]:
    _reject_brand_on_resume(resume, brand)
    if resume:
        target = target.resolve()
        _require_resumable(target, mode)
        return {"target": str(target), "mode": mode.value}

    with _pause_runtime_for_copy() if mode is DeploymentMode.COPY else nullcontext():
        plan = plan_deployment(source, target, mode)
        result: dict[str, object] = {
            "source": str(plan.source),
            "target": str(plan.target),
            "mode": mode.value,
            "journal": str(plan.target / "journal"),
            "memory": str(plan.target / "memory"),
            "brand": plan_brand(plan.source, mode, brand).preview(),
        }
        if plan.snapshot is not None:
            result["settings"] = [str(name) for name in plan.snapshot.config_files]
            result["source_journal"] = str(plan.snapshot.journal)
            result["source_memory"] = str(plan.snapshot.memory)
            for _ in snapshot_layers(plan.source, plan.snapshot):
                continue
        return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--mode", type=DeploymentMode, default=DeploymentMode.CLEAN)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--brand-check", action="store_true")
    parser.add_argument("--rebrand", action="store_true")
    args = parser.parse_args(argv)
    if args.rebrand and (args.resume or args.yes or args.preview or args.brand_check):
        parser.error(
            "--rebrand cannot be combined with --resume, --yes, --preview "
            "or --brand-check"
        )
    if args.brand_check and (args.resume or args.yes or args.preview):
        parser.error(
            "--brand-check cannot be combined with --resume, --yes or --preview"
        )
    if args.brand_check:
        answer = (
            check_home_brand(args.target, os.environ)
            if args.target is not None
            else check_brand_environment(args.source.resolve(), args.mode, os.environ)
        )
        print(BRAND_CHECK_PREFIX + json.dumps(answer), flush=True)
        return 0
    if args.target is None:
        parser.error("the following arguments are required: --target")
    try:
        if args.rebrand:
            return _rebrand(args.target)
        brand = request_from_environment(os.environ)
        if args.preview:
            result = preview_deployment(
                args.source, args.target, args.mode, resume=args.resume, brand=brand
            )
            print(PREVIEW_PREFIX + json.dumps(result), flush=True)
            return 0
        return deploy(
            args.source,
            args.target,
            mode=args.mode,
            resume=args.resume,
            assume_yes=args.yes,
            brand=brand,
        )
    except (DeploymentError, DeploymentPlanError, BrandStageError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


def _rebrand(home: Path) -> int:
    """A rejected request is an answer (exit 0); a half-applied one is an error."""
    try:
        result = rebrand_home(home, request_from_environment(os.environ))
    except DeploymentPlanError as error:
        answer: dict[str, object] = {"ok": False, "message": str(error)}
    else:
        answer = {
            "ok": True,
            "brand": result.brand,
            "files": list(result.files),
            **shortcut_result(home),
        }
    print(REBRAND_PREFIX + json.dumps(answer), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
