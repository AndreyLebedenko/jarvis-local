"""The read-only brand check the deployment wizard asks while the owner types.

It runs the deployment planner for the brand alone (no destination, no runtime
lock, nothing written) and answers with the resolved brand and what its icon
looks like, or with the planner's own message and the key it names.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path

from jarvis.core.brand_render import monogram_style
from tools.deployment_brand import (
    BrandPlan,
    BrandRequest,
    plan_brand,
    request_from_environment,
)
from tools.deployment_plan import DeploymentMode, DeploymentPlanError

BRAND_CHECK_PREFIX = "JARVIS_DEPLOY_BRAND_CHECK:"
PACKAGED_PNG = Path("src/jarvis/launcher/assets/jarvis.png")
_FIELD = re.compile(r"\[brand\]\.(name|monogram|accent|icon)")

Answer = dict[str, object]


def _rejected(message: str) -> Answer:
    named = _FIELD.search(message)
    return {
        "ok": False,
        "field": named.group(1) if named else None,
        "message": message,
    }


def _icon_preview(source: Path, plan: BrandPlan) -> dict[str, object]:
    if plan.is_default:
        return {"kind": "packaged", "path": str(source / PACKAGED_PNG)}
    if plan.brand.icon is None:
        return {"kind": "monogram", "art": asdict(monogram_style(plan.brand))}
    image = plan.external_icon or (source / plan.brand.icon).resolve()
    return {"kind": "image", "path": str(image)}


def check_brand(
    source: Path, mode: DeploymentMode, request: BrandRequest | None
) -> Answer:
    try:
        plan = plan_brand(source, mode, request)
    except DeploymentPlanError as error:
        return _rejected(str(error))
    return {
        "ok": True,
        "brand": plan.preview(),
        "icon_preview": _icon_preview(source, plan),
    }


def check_brand_environment(
    source: Path, mode: DeploymentMode, environment: Mapping[str, str]
) -> Answer:
    try:
        request = request_from_environment(environment)
    except DeploymentPlanError as error:
        return _rejected(str(error))
    return check_brand(source, mode, request)
