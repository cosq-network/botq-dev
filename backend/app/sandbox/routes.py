import pathlib

from flask import Blueprint, current_app, g, request

from ..api.responses import ok
from ..audit.service import record_audit
from ..errors import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    ValidationError,
)
from ..models import Project
from .readiness import build_readiness_report
from .runner import DockerSandboxRunner, SandboxDenied, SandboxUnavailable

bp = Blueprint("sandbox", __name__, url_prefix="/sandbox")


def _require_run_scope() -> None:
    from ..auth.roles import has_scope

    user = getattr(g, "user", None)
    if user is None or not has_scope(user, "sandbox:run"):
        from ..errors import AuthorizationError

        raise AuthorizationError("sandbox:run scope required")


def _require_read_scope() -> None:
    from ..auth.roles import has_scope

    user = getattr(g, "user", None)
    if user is None or not has_scope(user, "sandbox:read"):
        from ..errors import AuthorizationError

        raise AuthorizationError("sandbox:read scope required")


def _org():
    org = getattr(g, "organization", None)
    if org is None:
        raise AuthenticationError("Authenticated organization not found")
    return org


@bp.get("/readiness")
def readiness():
    _require_read_scope()
    report = build_readiness_report()
    org = getattr(g, "organization", None)
    record_audit(
        action="sandbox.readiness.checked",
        actor_id=str(g.user.id) if getattr(g, "user", None) else None,
        target_type="sandbox",
        organization_id=org.id if org else None,
        metadata={"mandatory_ok": report["mandatory_ok"]},
    )
    return ok(report)


@bp.post("/runs")
def run_isolated():
    _require_run_scope()
    payload = request.get_json(silent=True) or {}
    image = (payload.get("image") or "").strip()
    command = payload.get("command") or "/bin/sh -c 'echo diagnostics'"
    workspace = payload.get("workspace")
    cpu = payload.get("cpu")
    memory = payload.get("memory")
    timeout = payload.get("timeout")
    if not image:
        raise ValidationError("image is required (must be on the allowed list)")
    runner = DockerSandboxRunner(current_app)
    try:
        result = runner.run(
            image,
            command,
            workspace=workspace,
            cpu=cpu,
            memory=memory,
            timeout=timeout,
        )
    except SandboxDenied as exc:
        record_audit(
            action="sandbox.run.denied",
            actor_id=str(g.user.id),
            target_type="sandbox",
            organization_id=_org().id,
            metadata={"reason": str(exc)},
        )
        raise AuthorizationError(str(exc)) from None
    except SandboxUnavailable as exc:
        record_audit(
            action="sandbox.run.failed",
            actor_id=str(g.user.id),
            target_type="sandbox",
            organization_id=_org().id,
            metadata={"reason": str(exc)},
        )
        raise ConflictError(str(exc), code="sandbox_unavailable") from None
    record_audit(
        action="sandbox.run.completed",
        actor_id=str(g.user.id),
        target_type="sandbox",
        organization_id=_org().id,
        metadata={"image": image, "ok": result["ok"], "status_code": result["status_code"]},
    )
    return ok(result)


@bp.post("/diagnostic")
def diagnostic_run():
    _require_run_scope()
    payload = request.get_json(silent=True) or {}
    project_id = payload.get("project_id")
    if project_id:
        project = Project.query.filter_by(id=project_id, organization_id=_org().id).first()
        if project is None:
            from ..errors import NotFoundError

            raise NotFoundError("Project not found")
        workspace = pathlib.Path(current_app.config["SANDBOX_WORKSPACE_DIR"]) / str(project_id)
        workspace.mkdir(parents=True, exist_ok=True)
    else:
        workspace = None
    image = payload.get("image") or "python:3.13-slim"
    runner = DockerSandboxRunner(current_app)
    try:
        result = runner.readiness_probe(image)
    except (SandboxDenied, SandboxUnavailable) as exc:
        raise ConflictError(str(exc), code="diagnostic_failed") from None
    record_audit(
        action="sandbox.diagnostic_run.completed",
        actor_id=str(g.user.id),
        target_type="sandbox",
        organization_id=_org().id,
        metadata={"image": image, "ok": result["ok"]},
    )
    return ok(result)


@bp.post("/probe")
def probe():
    _require_run_scope()
    payload = request.get_json(silent=True) or {}
    command = (payload.get("command") or "").strip()
    if not command:
        raise ValidationError("command is required")
    image = (payload.get("image") or "python:3.13-slim").strip()
    runner = DockerSandboxRunner(current_app)
    try:
        result = runner.run(image, command, network="none")
    except (SandboxDenied, SandboxUnavailable) as exc:
        raise ConflictError(str(exc), code="probe_failed") from None
    record_audit(
        action="sandbox.probe.completed",
        actor_id=str(g.user.id),
        target_type="sandbox",
        organization_id=_org().id,
        metadata={"ok": result["ok"], "status_code": result["status_code"]},
    )
    return ok(result)
