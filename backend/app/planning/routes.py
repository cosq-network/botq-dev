import hashlib
import json
import posixpath
import uuid
from datetime import datetime

from flask import Blueprint, g, request

from ..api.responses import ok
from ..approvals.routes import _decide
from ..artifacts import service
from ..audit.service import record_audit
from ..errors import AuthenticationError, ConflictError, NotFoundError, ValidationError
from ..extensions import db
from ..models import (
    AgentCheckpoint,
    AgentRun,
    AgentRunEvent,
    Artifact,
    ArtifactVersion,
    ChangeSet,
    ChangeSetFile,
    VerificationRun,
)
from ..utils import new_uuid, utcnow

bp = Blueprint("planning", __name__)

PLAN_REQUIRED_SECTIONS = {
    "steps",
    "environment_manifest",
    "budget",
    "permissions",
    "escalation_rules",
    "feasibility",
}
RUN_STATUSES = {"queued", "running", "paused", "cancelled", "completed", "failed"}


@bp.post("/plans")
def create_plan():
    _require_plan_write()
    org = _org()
    payload = request.get_json(silent=True) or {}
    project_id = _uuid(payload.get("project_id"), "project_id")
    architecture_id = _uuid(payload.get("source_architecture_id"), "source_architecture_id")
    architecture = Artifact.query.filter_by(
        id=architecture_id,
        project_id=project_id,
        organization_id=org.id,
        artifact_type="architecture",
        status="approved",
    ).first()
    if architecture is None:
        raise ConflictError(
            "Technical planning requires an approved architecture", code="architecture_not_approved"
        )
    architecture_version = service.current_version(architecture)
    content = _validate_plan_content(payload.get("content"))
    title = (payload.get("title") or "").strip()
    if not title or len(title) > 200:
        raise ValidationError("title is required (max 200 characters)")
    artifact, version = service.new_artifact(
        organization_id=org.id,
        project_id=project_id,
        artifact_type="technical_plan",
        title=title,
        content=content,
        created_by=str(g.user.id),
    )
    artifact.source_artifact_id = architecture.id
    artifact.source_artifact_version = architecture.current_version
    artifact.source_artifact_hash = architecture_version.content_hash
    db.session.add_all([artifact, version])
    db.session.commit()
    _audit("technical_plan.created", artifact, {"architecture_id": str(architecture.id)})
    return ok(_serialize_plan(artifact, include_content=True), status=201)


@bp.get("/plans")
def list_plans():
    _require_plan_read()
    query = Artifact.query.filter_by(organization_id=_org().id, artifact_type="technical_plan")
    if request.args.get("project_id"):
        query = query.filter_by(project_id=_uuid(request.args["project_id"], "project_id"))
    return ok([_serialize_plan(item) for item in query.order_by(Artifact.created_at.desc()).all()])


@bp.get("/plans/<uuid:plan_id>")
def get_plan(plan_id):
    _require_plan_read()
    return ok(_serialize_plan(_get_plan(plan_id), include_content=True))


@bp.post("/plans/<uuid:plan_id>/versions")
def revise_plan(plan_id):
    _require_plan_write()
    org = _org()
    artifact = _get_plan(plan_id)
    if artifact.status == "cancelled":
        raise ConflictError("Cancelled plan cannot be revised", code="invalid_artifact_state")
    payload = request.get_json(silent=True) or {}
    content = _validate_plan_content(payload.get("content"))
    current = service.current_version(artifact)
    digest = service.content_hash(content)
    if digest == current.content_hash:
        raise ConflictError("The new content is identical to the current version", code="no_change")
    version = ArtifactVersion(
        id=new_uuid(),
        organization_id=org.id,
        artifact_id=artifact.id,
        version=artifact.current_version + 1,
        content=content,
        content_hash=digest,
        change_summary=payload.get("change_summary") or "revised technical plan",
        created_by=str(g.user.id),
    )
    artifact.current_version = version.version
    artifact.status = "draft"
    db.session.add(version)
    db.session.commit()
    _audit("technical_plan.version_created", artifact, {"version": version.version})
    return ok(_serialize_plan(artifact, include_content=True), status=201)


@bp.post("/plans/<uuid:plan_id>/submit")
def submit_plan(plan_id):
    _require_plan_write()
    artifact = _get_plan(plan_id)
    if artifact.status not in service.SUBMITTABLE_STATUSES:
        raise ConflictError("Plan is not in a submittable state", code="invalid_artifact_state")
    artifact.status = "submitted"
    db.session.commit()
    _audit("technical_plan.submitted", artifact, {})
    return ok(_serialize_plan(artifact, include_content=True))


@bp.post("/plans/<uuid:plan_id>/approve")
def approve_plan(plan_id):
    return _review_plan(plan_id, "approved")


@bp.post("/plans/<uuid:plan_id>/request-changes")
def request_changes_plan(plan_id):
    return _review_plan(plan_id, "changes_requested")


@bp.post("/plans/<uuid:plan_id>/reject")
def reject_plan(plan_id):
    return _review_plan(plan_id, "rejected")


@bp.post("/agent-runs")
def create_agent_run():
    _require_run_write()
    org = _org()
    payload = request.get_json(silent=True) or {}
    plan = _get_plan(_uuid(payload.get("plan_id"), "plan_id"))
    if plan.status != "approved":
        raise ConflictError(
            "Agent runs require an approved technical plan", code="plan_not_approved"
        )
    plan_version = service.current_version(plan)
    objective = (payload.get("objective") or "").strip()
    if not objective:
        raise ValidationError("objective is required")
    limits = payload.get("budget") or {}
    if not isinstance(limits, dict):
        raise ValidationError("budget must be an object")
    allowed_tools = _strings(payload.get("allowed_tools"), "allowed_tools")
    writable_paths = _paths(payload.get("writable_paths"))
    permissions = plan_version.content.get("permissions") or {}
    plan_tools = set(permissions.get("tools") or [])
    plan_paths = [_safe_path(value) for value in permissions.get("paths") or []]
    if any(tool not in plan_tools for tool in allowed_tools):
        raise ConflictError(
            "Agent run requested a tool outside the approved plan permissions",
            code="tool_out_of_scope",
        )
    if any(not _path_allowed(path, plan_paths) for path in writable_paths):
        raise ConflictError(
            "Agent run requested a writable path outside the approved plan permissions",
            code="path_out_of_scope",
        )
    environment = payload.get("environment") or {}
    model_config = payload.get("model_config") or {}
    if not isinstance(environment, dict):
        raise ValidationError("environment must be an object")
    if not isinstance(model_config, dict):
        raise ValidationError("model_config must be an object")
    run = AgentRun(
        id=new_uuid(),
        organization_id=org.id,
        project_id=plan.project_id,
        plan_artifact_id=plan.id,
        plan_version=plan.current_version,
        plan_hash=plan_version.content_hash,
        objective=objective,
        status="queued",
        allowed_tools=allowed_tools,
        writable_paths=writable_paths,
        environment=environment,
        model_config=model_config,
        budget=limits,
        created_by=str(g.user.id),
    )
    db.session.add(run)
    _event(run, "run_created", {"plan_version": run.plan_version, "plan_hash": run.plan_hash})
    db.session.commit()
    _audit("agent_run.created", run, {"plan_id": str(plan.id)})
    return ok(_serialize_run(run), status=201)


@bp.get("/agent-runs")
def list_agent_runs():
    _require_run_read()
    query = AgentRun.query.filter_by(organization_id=_org().id)
    if request.args.get("project_id"):
        query = query.filter_by(project_id=_uuid(request.args["project_id"], "project_id"))
    return ok([_serialize_run(run) for run in query.order_by(AgentRun.created_at.desc()).all()])


@bp.get("/agent-runs/<uuid:run_id>")
def get_agent_run(run_id):
    _require_run_read()
    return ok(_serialize_run(_get_run(run_id), include_events=True))


@bp.post("/agent-runs/<uuid:run_id>/start")
def start_agent_run(run_id):
    _require_run_write()
    run = _get_run(run_id)
    if run.status not in {"queued", "paused"}:
        raise ConflictError("Only queued or paused runs can start", code="invalid_run_state")
    _assert_plan_current(run)
    run.status = "running"
    run.worker_id = None
    run.lease_expires_at = None
    run.pause_reason = None
    _event(run, "run_started", {})
    db.session.commit()
    return ok(_serialize_run(run, include_events=True))


@bp.post("/agent-runs/<uuid:run_id>/pause")
def pause_agent_run(run_id):
    _require_run_write()
    run = _get_run(run_id)
    if run.status != "running":
        raise ConflictError("Only running runs can pause", code="invalid_run_state")
    reason = ((request.get_json(silent=True) or {}).get("reason") or "paused by operator").strip()
    run.status = "paused"
    run.worker_id = None
    run.lease_expires_at = None
    run.pause_reason = reason
    _event(run, "run_paused", {"reason": reason})
    db.session.commit()
    return ok(_serialize_run(run, include_events=True))


@bp.post("/agent-runs/<uuid:run_id>/cancel")
def cancel_agent_run(run_id):
    _require_run_write()
    run = _get_run(run_id)
    if run.status in {"completed", "failed", "cancelled"}:
        raise ConflictError("Run is already terminal", code="invalid_run_state")
    run.status = "cancelled"
    run.worker_id = None
    run.lease_expires_at = None
    _event(run, "run_cancelled", {})
    db.session.commit()
    return ok(_serialize_run(run, include_events=True))


@bp.post("/agent-runs/<uuid:run_id>/checkpoints")
def checkpoint_agent_run(run_id):
    _require_run_write()
    run = _get_run(run_id)
    if run.status not in {"running", "paused"}:
        raise ConflictError("Only active runs can checkpoint", code="invalid_run_state")
    payload = request.get_json(silent=True) or {}
    state = payload.get("state")
    if not isinstance(state, dict):
        raise ValidationError("state must be an object")
    sequence = (run.checkpoints[-1].sequence if run.checkpoints else 0) + 1
    checkpoint = AgentCheckpoint(
        id=new_uuid(),
        organization_id=_org().id,
        run_id=run.id,
        sequence=sequence,
        state=state,
        evidence=payload.get("evidence") or {},
    )
    run.current_step = payload.get("current_step") or run.current_step
    db.session.add(checkpoint)
    _event(run, "checkpoint_created", {"sequence": sequence})
    db.session.commit()
    return ok(_serialize_checkpoint(checkpoint), status=201)


@bp.post("/agent-runs/<uuid:run_id>/change-sets")
def create_change_set(run_id):
    _require_changeset_write()
    org = _org()
    run = _get_run(run_id)
    if run.status not in {"running", "paused", "completed"}:
        raise ConflictError("Run is not ready to produce a change set", code="invalid_run_state")
    _assert_plan_current(run)
    payload = request.get_json(silent=True) or {}
    branch = (payload.get("branch") or "").strip()
    base_commit = (payload.get("base_commit") or "").strip()
    if not branch or not base_commit:
        raise ValidationError("branch and base_commit are required")
    change_set = ChangeSet(
        id=new_uuid(),
        organization_id=org.id,
        project_id=run.project_id,
        run_id=run.id,
        plan_artifact_id=run.plan_artifact_id,
        plan_version=run.plan_version,
        plan_hash=run.plan_hash,
        branch=branch,
        base_commit=base_commit,
        status="draft",
        created_by=str(g.user.id),
    )
    db.session.add(change_set)
    db.session.commit()
    _audit("change_set.created", change_set, {"run_id": str(run.id)})
    return ok(_serialize_change_set(change_set), status=201)


@bp.post("/change-sets/<uuid:change_set_id>/files")
def add_change_set_file(change_set_id):
    _require_changeset_write()
    change_set = _get_change_set(change_set_id)
    if change_set.status != "draft":
        raise ConflictError("Only draft change sets can be edited", code="invalid_change_set_state")
    payload = request.get_json(silent=True) or {}
    path = _safe_path(payload.get("path"))
    if not _path_allowed(path, change_set.run.writable_paths):
        _event(change_set.run, "policy_violation", {"path": path, "reason": "path_out_of_scope"})
        db.session.commit()
        raise ConflictError(
            "Path is outside the approved writable boundary", code="path_out_of_scope"
        )
    action = (payload.get("action") or "modify").strip().lower()
    if action not in {"add", "modify", "delete"}:
        raise ValidationError("action must be add, modify or delete")
    diff = payload.get("diff")
    if not isinstance(diff, str) or not diff:
        raise ValidationError("diff is required")
    content_hash = hashlib.sha256(diff.encode("utf-8")).hexdigest()
    existing = ChangeSetFile.query.filter_by(change_set_id=change_set.id, path=path).first()
    if existing:
        raise ConflictError(
            "A file with this path is already recorded", code="duplicate_change_path"
        )
    db.session.add(
        ChangeSetFile(
            id=new_uuid(),
            organization_id=_org().id,
            change_set_id=change_set.id,
            path=path,
            action=action,
            diff=diff,
            content_hash=content_hash,
        )
    )
    db.session.commit()
    return ok(_serialize_change_set(change_set), status=201)


@bp.post("/change-sets/<uuid:change_set_id>/self-review")
def self_review_change_set(change_set_id):
    _require_changeset_write()
    change_set = _get_change_set(change_set_id)
    if change_set.status != "draft":
        raise ConflictError(
            "Only draft change sets can be reviewed", code="invalid_change_set_state"
        )
    if not change_set.files:
        raise ConflictError("A change set must contain at least one file", code="empty_change_set")
    payload = request.get_json(silent=True) or {}
    review = payload.get("review")
    if not isinstance(review, dict) or not review.get("result"):
        raise ValidationError("review.result is required")
    change_set.self_review = review
    change_set.diff_hash = _change_set_hash(change_set)
    change_set.status = "review"
    db.session.commit()
    return ok(_serialize_change_set(change_set))


@bp.post("/change-sets/<uuid:change_set_id>/submit")
def submit_change_set(change_set_id):
    _require_changeset_write()
    change_set = _get_change_set(change_set_id)
    if change_set.status != "review":
        raise ConflictError(
            "Self-review is required before submission", code="invalid_change_set_state"
        )
    now = utcnow()
    if not change_set.verifications or any(
        item.status == "failed"
        or (item.status == "waived" and not item.waiver_expires_at)
        or (
            item.status == "waived"
            and item.waiver_expires_at is not None
            and item.waiver_expires_at <= now
        )
        or item.change_set_hash != change_set.diff_hash
        for item in change_set.verifications
    ):
        raise ConflictError(
            "All verification runs must pass before submission", code="verification_required"
        )
    change_set.status = "submitted"
    db.session.commit()
    return ok(_serialize_change_set(change_set))


@bp.post("/change-sets/<uuid:change_set_id>/approve")
def approve_change_set(change_set_id):
    _require_changeset_read()
    payload = request.get_json(silent=True) or {}
    _decide("change_set", change_set_id, "approved", payload)
    return ok(_serialize_change_set(_get_change_set(change_set_id)))


@bp.post("/change-sets/<uuid:change_set_id>/verifications")
def record_verification(change_set_id):
    _require_run_write()
    change_set = _get_change_set(change_set_id)
    if change_set.status not in {"review", "submitted"} or not change_set.diff_hash:
        raise ConflictError(
            "Self-review must produce a change-set hash before verification",
            code="change_set_review_required",
        )
    payload = request.get_json(silent=True) or {}
    kind = (payload.get("kind") or "test").strip().lower()
    status = (payload.get("status") or "").strip().lower()
    command = (payload.get("command") or "").strip()
    if kind not in {"test", "dependency", "secret", "license", "sast", "image"}:
        raise ValidationError("unsupported verification kind")
    if status not in {"passed", "failed", "waived"} or not command:
        raise ValidationError("command and status (passed, failed or waived) are required")
    result = payload.get("result") or {}
    if not isinstance(result, dict):
        raise ValidationError("result must be an object")
    if result.get("change_set_hash") != change_set.diff_hash:
        raise ConflictError(
            "Verification evidence must identify the current change-set hash",
            code="stale_verification_evidence",
        )
    waiver_reason = (payload.get("reason") or "").strip() or None
    waiver_expires_at = None
    if status == "waived":
        from ..auth.roles import has_scope

        if not has_scope(g.user, "approval"):
            raise AuthenticationError("approval scope required to waive verification")
        if not waiver_reason or not payload.get("expires_at"):
            raise ValidationError("A waived verification requires reason and expires_at")
        try:
            waiver_expires_at = datetime.fromisoformat(
                str(payload["expires_at"]).replace("Z", "+00:00")
            )
            if waiver_expires_at.tzinfo is not None:
                waiver_expires_at = waiver_expires_at.replace(tzinfo=None)
        except ValueError as exc:
            raise ValidationError("expires_at must be an ISO-8601 datetime") from exc
        if waiver_expires_at <= utcnow():
            raise ValidationError("expires_at must be in the future")
    evidence_hash = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    verification = VerificationRun(
        id=new_uuid(),
        organization_id=_org().id,
        project_id=change_set.project_id,
        change_set_id=change_set.id,
        kind=kind,
        command=command,
        status=status,
        result=result,
        evidence_hash=evidence_hash,
        change_set_hash=change_set.diff_hash,
        waiver_reason=waiver_reason,
        waiver_expires_at=waiver_expires_at,
        started_at=utcnow(),
        finished_at=utcnow(),
        created_by=str(g.user.id),
    )
    db.session.add(verification)
    # Late evidence may be attached while a change set is awaiting approval.
    # A non-passing result invalidates that submission and returns it to review;
    # evidence can never be appended after approval.
    if change_set.status == "submitted" and status != "passed":
        change_set.status = "review"
    db.session.commit()
    return ok(_serialize_verification(verification), status=201)


def _review_plan(plan_id, decision):
    _require_plan_read()
    payload = request.get_json(silent=True) or {}
    _decide("technical_plan", plan_id, decision, payload)
    return ok(_serialize_plan(_get_plan(plan_id), include_content=True))


def _assert_plan_current(run):
    plan = Artifact.query.filter_by(
        id=run.plan_artifact_id, organization_id=_org().id, artifact_type="technical_plan"
    ).first()
    if plan is None or plan.status != "approved":
        raise ConflictError("The approved plan is no longer available", code="stale_plan")
    version = service.current_version(plan)
    if plan.current_version != run.plan_version or version.content_hash != run.plan_hash:
        raise ConflictError("The plan changed after this run was created", code="stale_plan")


def _change_set_hash(change_set):
    content = [
        {"path": item.path, "action": item.action, "content_hash": item.content_hash}
        for item in change_set.files
    ]
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _event(run, event_type, payload):
    sequence = (run.events[-1].sequence if run.events else 0) + 1
    db.session.add(
        AgentRunEvent(
            id=new_uuid(),
            organization_id=run.organization_id,
            run_id=run.id,
            sequence=sequence,
            event_type=event_type,
            payload=payload,
        )
    )


def _serialize_plan(artifact, *, include_content=False):
    data = service.serialize_artifact(artifact, include_content=include_content)
    data["source_architecture"] = {
        "artifact_id": str(artifact.source_artifact_id),
        "version": artifact.source_artifact_version,
        "hash": artifact.source_artifact_hash,
    }
    return data


def _validate_plan_content(raw):
    content = service.normalize_content(raw)
    missing = sorted(PLAN_REQUIRED_SECTIONS - set(content))
    if missing:
        raise ValidationError(f"Plan content is missing sections: {', '.join(missing)}")
    steps = content["steps"]
    if not isinstance(steps, list) or not steps:
        raise ValidationError("steps must be a non-empty list")
    step_ids = set()
    for step in steps:
        if not isinstance(step, dict):
            raise ValidationError("each plan step must be an object")
        for field in ("id", "title", "validation"):
            if not isinstance(step.get(field), str) or not step[field].strip():
                raise ValidationError(f"each plan step requires {field}")
        if step["id"] in step_ids:
            raise ValidationError("plan step ids must be unique")
        step_ids.add(step["id"])
    manifest = content["environment_manifest"]
    if not isinstance(manifest, dict):
        raise ValidationError("environment_manifest must be an object")
    allowed_types = {"string", "integer", "number", "boolean", "url", "path", "json"}
    for name, spec in manifest.items():
        if not isinstance(name, str) or not name or not name.replace("_", "").isalnum():
            raise ValidationError("environment variable names must be alphanumeric/underscore")
        if not isinstance(spec, dict) or spec.get("type") not in allowed_types:
            raise ValidationError(
                f"environment variable {name} requires a supported type declaration"
            )
        if not isinstance(spec.get("required", False), bool) or not isinstance(
            spec.get("secret", False), bool
        ):
            raise ValidationError(f"environment variable {name} required/secret must be boolean")
    for field in ("budget", "permissions", "feasibility"):
        if not isinstance(content[field], dict):
            raise ValidationError(f"{field} must be an object")
    permissions = content["permissions"]
    for field in ("tools", "paths"):
        if not isinstance(permissions.get(field), list) or not all(
            isinstance(value, str) and value.strip() for value in permissions[field]
        ):
            raise ValidationError(f"permissions.{field} must be a list of non-empty strings")
    for path in permissions["paths"]:
        _safe_path(path)
    for field in ("max_minutes", "max_cost"):
        if field in content["budget"]:
            try:
                if float(content["budget"][field]) <= 0:
                    raise ValueError
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"budget.{field} must be positive") from exc
    if not isinstance(content["escalation_rules"], list) or not all(
        isinstance(value, str) and value.strip() for value in content["escalation_rules"]
    ):
        raise ValidationError("escalation_rules must be a list of non-empty strings")
    return content


def _serialize_run(run, *, include_events=False):
    data = {
        "id": str(run.id),
        "project_id": str(run.project_id),
        "plan_id": str(run.plan_artifact_id),
        "plan_version": run.plan_version,
        "plan_hash": run.plan_hash,
        "objective": run.objective,
        "status": run.status,
        "current_step": run.current_step,
        "allowed_tools": run.allowed_tools,
        "writable_paths": run.writable_paths,
        "environment": run.environment,
        "model_config": run.model_config,
        "budget": run.budget,
        "worker_id": run.worker_id,
        "lease_expires_at": run.lease_expires_at.isoformat() if run.lease_expires_at else None,
        "attempt_count": run.attempt_count,
        "pause_reason": run.pause_reason,
        "checkpoint_count": len(run.checkpoints),
        "created_by": run.created_by,
        "created_at": run.created_at.isoformat(),
    }
    if include_events:
        data["events"] = [
            {"sequence": item.sequence, "type": item.event_type, "payload": item.payload}
            for item in run.events
        ]
        data["checkpoints"] = [_serialize_checkpoint(item) for item in run.checkpoints]
    return data


def _serialize_checkpoint(checkpoint):
    return {
        "id": str(checkpoint.id),
        "sequence": checkpoint.sequence,
        "state": checkpoint.state,
        "evidence": checkpoint.evidence,
        "created_at": checkpoint.created_at.isoformat(),
    }


def _serialize_change_set(change_set):
    return {
        "id": str(change_set.id),
        "project_id": str(change_set.project_id),
        "run_id": str(change_set.run_id),
        "plan_id": str(change_set.plan_artifact_id),
        "plan_version": change_set.plan_version,
        "plan_hash": change_set.plan_hash,
        "branch": change_set.branch,
        "base_commit": change_set.base_commit,
        "status": change_set.status,
        "diff_hash": change_set.diff_hash,
        "self_review": change_set.self_review,
        "files": [
            {"path": item.path, "action": item.action, "content_hash": item.content_hash}
            for item in change_set.files
        ],
        "verifications": [_serialize_verification(item) for item in change_set.verifications],
        "created_by": change_set.created_by,
        "created_at": change_set.created_at.isoformat(),
    }


def _serialize_verification(item):
    return {
        "id": str(item.id),
        "kind": item.kind,
        "command": item.command,
        "status": item.status,
        "result": item.result,
        "evidence_hash": item.evidence_hash,
        "change_set_hash": item.change_set_hash,
        "waiver_reason": item.waiver_reason,
        "waiver_expires_at": item.waiver_expires_at.isoformat() if item.waiver_expires_at else None,
        "created_by": item.created_by,
        "created_at": item.created_at.isoformat(),
    }


def _get_plan(plan_id):
    item = Artifact.query.filter_by(
        id=plan_id, organization_id=_org().id, artifact_type="technical_plan"
    ).first()
    if item is None:
        raise NotFoundError("Technical plan not found")
    return item


def _get_run(run_id):
    item = AgentRun.query.filter_by(id=run_id, organization_id=_org().id).first()
    if item is None:
        raise NotFoundError("Agent run not found")
    return item


def _get_change_set(change_set_id):
    item = ChangeSet.query.filter_by(id=change_set_id, organization_id=_org().id).first()
    if item is None:
        raise NotFoundError("Change set not found")
    return item


def _safe_path(value):
    path = str(value or "").replace("\\", "/")
    if not path or path.startswith("/") or path.startswith("~"):
        raise ValidationError("path must be a relative workspace path")
    normalized = posixpath.normpath(path)
    if normalized in {".", ".."} or normalized.startswith("../"):
        raise ValidationError("path cannot escape the workspace")
    return normalized


def _path_allowed(path, allowed):
    if not allowed:
        return False
    return any(path == prefix or path.startswith(prefix.rstrip("/") + "/") for prefix in allowed)


def _strings(raw, field):
    if raw is None:
        return []
    if not isinstance(raw, list) or any(
        not isinstance(value, str) or not value.strip() for value in raw
    ):
        raise ValidationError(f"{field} must be a list of non-empty strings")
    return [value.strip() for value in raw]


def _paths(raw):
    return [_safe_path(value) for value in _strings(raw, "writable_paths")]


def _uuid(value, field):
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValidationError(f"{field} must be a valid UUID") from exc


def _org():
    org = getattr(g, "organization", None)
    if org is None:
        raise AuthenticationError("Authenticated organization not found")
    return org


def _require_plan_read():
    from ..auth.roles import has_scope

    if g.user is None or not has_scope(g.user, "plan:read"):
        raise AuthenticationError("plan:read scope required")


def _require_plan_write():
    from ..auth.roles import has_scope

    if g.user is None or not has_scope(g.user, "plan:write"):
        raise AuthenticationError("plan:write scope required")


def _require_run_read():
    from ..auth.roles import has_scope

    if g.user is None or not has_scope(g.user, "agent_run:read"):
        raise AuthenticationError("agent_run:read scope required")


def _require_run_write():
    from ..auth.roles import has_scope

    if g.user is None or not has_scope(g.user, "agent_run:run"):
        raise AuthenticationError("agent_run:run scope required")


def _require_changeset_read():
    from ..auth.roles import has_scope

    if g.user is None or not has_scope(g.user, "changeset:read"):
        raise AuthenticationError("changeset:read scope required")


def _require_changeset_write():
    from ..auth.roles import has_scope

    if g.user is None or not has_scope(g.user, "changeset:write"):
        raise AuthenticationError("changeset:write scope required")


def _audit(action, target, metadata):
    record_audit(
        action=action,
        actor_id=str(g.user.id),
        target_type=target.__class__.__tablename__.rstrip("s"),
        target_id=target.id,
        organization_id=_org().id,
        metadata=metadata,
    )
