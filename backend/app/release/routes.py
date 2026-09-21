from __future__ import annotations

import hashlib
import json
import re
import uuid

from flask import Blueprint, current_app, g, request

from ..api.responses import ok
from ..approvals.routes import _decide
from ..audit.service import record_audit
from ..errors import AuthenticationError, ConflictError, NotFoundError, ValidationError
from ..extensions import db
from ..models import (
    AcceptanceSession,
    Approval,
    ChangeSet,
    Defect,
    Deployment,
    DeploymentPlan,
    Release,
    ReleaseReadinessCheck,
    VerificationRun,
)
from ..utils import new_uuid, utcnow
from .adapter import (
    DeploymentProviderError,
    LocalComposeDeploymentAdapter,
    WebhookDeploymentAdapter,
)

bp = Blueprint("release", __name__)

RELEASE_STATUSES = {"draft", "submitted", "approved", "packaged", "cancelled"}
PLAN_STATUSES = {"draft", "submitted", "approved", "rejected", "cancelled"}
CHECK_STATUSES = {"passed", "failed", "waived", "na"}
PLAN_SECTIONS = {
    "prechecks",
    "migrations",
    "deployment_steps",
    "health_checks",
    "rollback_triggers",
    "recovery_steps",
}
SEMVER = re.compile(r"^v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


@bp.post("/releases")
def create_release():
    _require("release:write")
    payload = request.get_json(silent=True) or {}
    change_set = _change_set(_uuid(payload.get("change_set_id"), "change_set_id"))
    if change_set.status != "approved":
        raise ConflictError(
            "A release requires an approved change set", code="change_set_not_approved"
        )
    version = (payload.get("version") or "").strip()
    if not SEMVER.fullmatch(version):
        raise ValidationError("version must be semantic version format, for example 1.2.3")
    commit_sha = (payload.get("commit_sha") or "").strip()
    if not commit_sha:
        raise ValidationError("commit_sha is required")
    if Release.query.filter_by(project_id=change_set.project_id, version=version).first():
        raise ConflictError("A release with this version already exists", code="duplicate_release")
    rollback = payload.get("rollback") or {}
    if not isinstance(rollback, dict):
        raise ValidationError("rollback must be an object")
    identity = {
        "version": version,
        "commit_sha": commit_sha,
        "change_set_id": str(change_set.id),
        "change_set_hash": change_set.diff_hash,
    }
    release = Release(
        id=new_uuid(),
        organization_id=_org().id,
        project_id=change_set.project_id,
        change_set_id=change_set.id,
        version=version,
        commit_sha=commit_sha,
        release_notes=str(payload.get("release_notes") or "").strip(),
        content_hash=_hash(identity),
        status="draft",
        rollback=rollback,
        created_by=str(g.user.id),
    )
    db.session.add(release)
    db.session.commit()
    _audit("release.created", release, {"version": version, "commit_sha": commit_sha})
    return ok(_serialize_release(release), status=201)


@bp.get("/releases")
def list_releases():
    _require("release:read")
    query = Release.query.filter_by(organization_id=_org().id)
    if request.args.get("project_id"):
        query = query.filter_by(project_id=_uuid(request.args["project_id"], "project_id"))
    return ok(
        [_serialize_release(item) for item in query.order_by(Release.created_at.desc()).all()]
    )


@bp.get("/releases/<uuid:release_id>")
def get_release(release_id):
    _require("release:read")
    return ok(_serialize_release(_get_release(release_id)))


@bp.post("/releases/<uuid:release_id>/readiness")
def evaluate_readiness(release_id):
    _require("release:write")
    release = _get_release(release_id)
    if release.status not in {"draft", "submitted"}:
        raise ConflictError(
            "Readiness can only be evaluated before approval", code="invalid_release_state"
        )
    supplied = request.get_json(silent=True) or {}
    explicit = supplied.get("checks") or []
    if not isinstance(explicit, list):
        raise ValidationError("checks must be a list")
    checks = _automatic_checks(release)
    known = {item["key"] for item in checks}
    for item in explicit:
        if not isinstance(item, dict):
            raise ValidationError("each readiness check must be an object")
        key = str(item.get("key") or "").strip()
        if not key or key in known:
            raise ValidationError("readiness check keys must be unique and non-empty")
        status = str(item.get("status") or "").strip().lower()
        if status not in CHECK_STATUSES:
            raise ValidationError("readiness check status must be passed, failed, waived or na")
        if status == "waived" and not str(item.get("reason") or "").strip():
            raise ValidationError("waived readiness checks require a reason")
        checks.append(
            {
                "key": key,
                "category": str(item.get("category") or "external"),
                "mandatory": item.get("mandatory", True) is not False,
                "status": status,
                "detail": str(item.get("detail") or ""),
                "evidence": item.get("evidence") or {},
            }
        )
        known.add(key)
    ReleaseReadinessCheck.query.filter_by(release_id=release.id).delete()
    for item in checks:
        db.session.add(
            ReleaseReadinessCheck(
                id=new_uuid(),
                organization_id=release.organization_id,
                project_id=release.project_id,
                release_id=release.id,
                key=item["key"],
                category=item["category"],
                mandatory=item["mandatory"],
                status=item["status"],
                detail=item["detail"],
                evidence=item["evidence"] if isinstance(item["evidence"], dict) else {},
                created_by=str(g.user.id),
            )
        )
    blocking = [
        item["key"]
        for item in checks
        if item["mandatory"] and item["status"] not in {"passed", "waived"}
    ]
    release.readiness = {
        "evaluated_at": utcnow().isoformat(),
        "passed": not blocking,
        "blocking": blocking,
        "check_count": len(checks),
    }
    release.status = "draft" if blocking else "submitted"
    db.session.commit()
    _audit(
        "release.readiness_evaluated",
        release,
        {"passed": not blocking, "blocking": blocking, "check_count": len(checks)},
    )
    return ok(_serialize_release(release))


@bp.post("/releases/<uuid:release_id>/approve")
def approve_release(release_id):
    _require("release:read")
    return _review_release(release_id, "approved")


@bp.post("/releases/<uuid:release_id>/package")
def package_release(release_id):
    _require("release:write")
    release = _get_release(release_id)
    if release.status != "approved":
        raise ConflictError("Only an approved release can be packaged", code="release_not_approved")
    if not release.readiness.get("passed"):
        raise ConflictError("Release readiness has not passed", code="readiness_required")
    manifest = {
        "release_id": str(release.id),
        "version": release.version,
        "commit_sha": release.commit_sha,
        "change_set_id": str(release.change_set_id),
        "change_set_hash": release.change_set.diff_hash,
        "release_content_hash": release.content_hash,
        "release_notes": release.release_notes,
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    release.package = {
        "manifest": manifest,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "immutable_identifier": f"{release.version}@{release.commit_sha}",
        "created_at": utcnow().isoformat(),
    }
    release.status = "packaged"
    db.session.commit()
    _audit("release.packaged", release, {"manifest_sha256": release.package["manifest_sha256"]})
    return ok(_serialize_release(release))


@bp.post("/deployment-plans")
def create_deployment_plan():
    _require("deployment:write")
    payload = request.get_json(silent=True) or {}
    release = _get_release(_uuid(payload.get("release_id"), "release_id"))
    if release.status != "packaged":
        raise ConflictError(
            "Deployment plans require a packaged release", code="release_not_packaged"
        )
    environment = str(payload.get("environment") or "").strip().lower()
    if environment not in {"staging", "production"}:
        raise ValidationError("environment must be staging or production")
    content = _validate_plan(payload.get("content"))
    plan = DeploymentPlan(
        id=new_uuid(),
        organization_id=release.organization_id,
        project_id=release.project_id,
        release_id=release.id,
        environment=environment,
        version=1,
        content=content,
        content_hash=_hash(content),
        status="draft",
        created_by=str(g.user.id),
    )
    db.session.add(plan)
    db.session.commit()
    _audit(
        "deployment_plan.created", plan, {"release_id": str(release.id), "environment": environment}
    )
    return ok(_serialize_plan(plan, include_content=True), status=201)


@bp.get("/deployment-plans")
def list_deployment_plans():
    _require("deployment:read")
    query = DeploymentPlan.query.filter_by(organization_id=_org().id)
    if request.args.get("release_id"):
        query = query.filter_by(release_id=_uuid(request.args["release_id"], "release_id"))
    return ok(
        [_serialize_plan(item) for item in query.order_by(DeploymentPlan.created_at.desc()).all()]
    )


@bp.get("/deployment-plans/<uuid:plan_id>")
def get_deployment_plan(plan_id):
    _require("deployment:read")
    return ok(_serialize_plan(_get_plan(plan_id), include_content=True))


@bp.post("/deployment-plans/<uuid:plan_id>/submit")
def submit_deployment_plan(plan_id):
    _require("deployment:write")
    plan = _get_plan(plan_id)
    if plan.status != "draft":
        raise ConflictError(
            "Only draft deployment plans can be submitted", code="invalid_plan_state"
        )
    plan.status = "submitted"
    db.session.commit()
    _audit("deployment_plan.submitted", plan, {})
    return ok(_serialize_plan(plan))


@bp.post("/deployment-plans/<uuid:plan_id>/approve")
def approve_deployment_plan(plan_id):
    _require("deployment:read")
    payload = request.get_json(silent=True) or {}
    _decide("deployment_plan", plan_id, "approved", payload)
    return ok(_serialize_plan(_get_plan(plan_id)))


@bp.post("/deployments")
def create_deployment():
    _require("deployment:write")
    payload = request.get_json(silent=True) or {}
    plan = _get_plan(_uuid(payload.get("deployment_plan_id"), "deployment_plan_id"))
    release = plan.release
    if plan.status != "approved" or release.status != "packaged":
        raise ConflictError(
            "Deployment requires an approved plan and packaged release",
            code="deployment_not_authorized",
        )
    if not release.readiness.get("passed"):
        raise ConflictError("Release readiness has not passed", code="readiness_required")
    _require_production_dual_control(plan)
    deployment = Deployment(
        id=new_uuid(),
        organization_id=release.organization_id,
        project_id=release.project_id,
        release_id=release.id,
        deployment_plan_id=plan.id,
        environment=plan.environment,
        status="queued",
        provider="webhook",
        rollback={"previous": release.rollback.get("previous_deployable_version")},
        created_by=str(g.user.id),
    )
    db.session.add(deployment)
    db.session.commit()
    if payload.get("execute") is True:
        _execute_deployment(deployment)
    else:
        _audit("deployment.authorized", deployment, {"executed": False})
    return ok(_serialize_deployment(deployment), status=201)


@bp.get("/deployments")
def list_deployments():
    _require("deployment:read")
    query = Deployment.query.filter_by(organization_id=_org().id)
    return ok(
        [_serialize_deployment(item) for item in query.order_by(Deployment.created_at.desc()).all()]
    )


@bp.get("/deployments/<uuid:deployment_id>")
def get_deployment(deployment_id):
    _require("deployment:read")
    return ok(_serialize_deployment(_get_deployment(deployment_id)))


@bp.post("/deployments/<uuid:deployment_id>/rollback")
def rollback_deployment(deployment_id):
    _require("deployment:write")
    deployment = _get_deployment(deployment_id)
    if deployment.status not in {"healthy", "failed"}:
        raise ConflictError(
            "Only healthy or failed deployments can roll back", code="invalid_deployment_state"
        )
    adapter = _deployment_adapter()
    try:
        result = adapter.rollback(_deployment_manifest(deployment, action="rollback"))
    except DeploymentProviderError:
        deployment.rollback = {
            **deployment.rollback,
            "status": "failed",
            "attempted_at": utcnow().isoformat(),
        }
        db.session.commit()
        raise
    deployment.status = "rolled_back" if result.status != "failed" else "failed"
    deployment.rollback = {
        **deployment.rollback,
        "status": deployment.status,
        "provider_id": result.provider_id,
        "diagnostics": result.diagnostics,
    }
    deployment.finished_at = utcnow()
    db.session.commit()
    _audit("deployment.rollback", deployment, {"status": deployment.status})
    return ok(_serialize_deployment(deployment))


def _automatic_checks(release):
    checks = []
    change_set = release.change_set
    checks.append(
        _check(
            "change_set_approval",
            "approval",
            True,
            change_set.status == "approved",
            "Change set approval is required",
        )
    )
    now = utcnow()
    verifications = VerificationRun.query.filter_by(change_set_id=change_set.id).all()
    verification_ok = bool(verifications) and all(
        item.change_set_hash == change_set.diff_hash
        and (
            item.status == "passed"
            or (
                item.status == "waived"
                and item.waiver_expires_at is not None
                and item.waiver_expires_at > now
            )
        )
        for item in verifications
    )
    checks.append(
        _check(
            "verification_evidence",
            "verification",
            True,
            verification_ok,
            "All verification evidence must pass or have an unexpired waiver",
        )
    )
    open_defects = Defect.query.filter(
        Defect.organization_id == release.organization_id,
        Defect.project_id == release.project_id,
        Defect.severity.in_({"critical", "high"}),
        Defect.status != "closed",
    ).count()
    checks.append(
        _check(
            "blocking_defects",
            "quality",
            True,
            open_defects == 0,
            f"{open_defects} blocking defect(s) remain open",
        )
    )
    previews = release.change_set.id
    sessions = (
        AcceptanceSession.query.join(AcceptanceSession.preview)
        .filter_by(change_set_id=previews)
        .all()
    )
    if sessions:
        acceptance_ok = any(session.status == "accepted" for session in sessions)
        checks.append(
            _check(
                "human_acceptance",
                "acceptance",
                True,
                acceptance_ok,
                "An accepted HAT session is required",
            )
        )
    else:
        checks.append(
            _check(
                "human_acceptance",
                "acceptance",
                False,
                True,
                "No preview is bound to this change set",
            )
        )
    rollback_ok = bool(release.rollback.get("previous_deployable_version")) and bool(
        release.rollback.get("instructions")
    )
    checks.append(
        _check(
            "rollback_prerequisites",
            "rollback",
            True,
            rollback_ok,
            "Previous deployable version and rollback instructions are required",
        )
    )
    return checks


def _check(key, category, mandatory, passed, detail):
    return {
        "key": key,
        "category": category,
        "mandatory": mandatory,
        "status": "passed" if passed else "failed",
        "detail": detail,
        "evidence": {},
    }


def _execute_deployment(deployment):
    deployment.status = "running"
    deployment.started_at = utcnow()
    db.session.commit()
    try:
        result = _deployment_adapter().provision(_deployment_manifest(deployment, action="deploy"))
    except DeploymentProviderError as exc:
        deployment.status = "failed"
        deployment.diagnostics = {"error": str(exc)}
        deployment.finished_at = utcnow()
        db.session.commit()
        _audit("deployment.failed", deployment, {"error": str(exc)})
        raise
    deployment.status = result.status
    deployment.provider_id = result.provider_id
    deployment.diagnostics = result.diagnostics
    deployment.health_checks = result.health_checks
    deployment.finished_at = (
        utcnow() if result.status in {"healthy", "failed", "rolled_back"} else None
    )
    db.session.commit()
    _audit("deployment.completed", deployment, {"status": deployment.status})


def _deployment_manifest(deployment, *, action):
    release = deployment.release
    return {
        "action": action,
        "deployment_id": str(deployment.id),
        "release_id": str(release.id),
        "version": release.version,
        "commit_sha": release.commit_sha,
        "environment": deployment.environment,
        "deployment_plan_id": str(deployment.deployment_plan_id),
        "plan_version": deployment.deployment_plan.version,
        "plan_hash": deployment.deployment_plan.content_hash,
        "plan": deployment.deployment_plan.content,
        "rollback": release.rollback,
    }


def _deployment_adapter():
    factory = current_app.config.get("DEPLOYMENT_ADAPTER_FACTORY")
    if factory:
        return factory()
    if current_app.config.get("DEPLOYMENT_ADAPTER") == "local_compose":
        if current_app.config.get("ENVIRONMENT", "").lower() == "production":
            raise ConflictError("Local Compose deployment is forbidden in production")
        return LocalComposeDeploymentAdapter(current_app.config)
    return WebhookDeploymentAdapter(current_app.config)


def _require_production_dual_control(plan):
    if plan.environment != "production":
        return
    approvals = Approval.query.filter_by(
        organization_id=plan.organization_id,
        artifact_type="deployment_plan",
        artifact_id=str(plan.id),
        decision="approved",
    ).all()
    deciders = {item.decider_id for item in approvals}
    roles = [set(item.decider_roles or []) for item in approvals]
    release_approved = any(
        "release_manager" in item or "organization_administrator" in item for item in roles
    )
    security_approved = any(
        "security_approver" in item or "organization_administrator" in item for item in roles
    )
    if len(deciders) < 2 or not release_approved or not security_approved:
        raise ConflictError(
            "Production deployment requires distinct release-manager and security approvals",
            code="dual_control_required",
        )


def _review_release(release_id, decision):
    payload = request.get_json(silent=True) or {}
    _decide("release", release_id, decision, payload)
    return ok(_serialize_release(_get_release(release_id)))


def _validate_plan(raw):
    if not isinstance(raw, dict):
        raise ValidationError("content must be an object")
    missing = sorted(PLAN_SECTIONS - set(raw))
    if missing:
        raise ValidationError(f"deployment plan content is missing sections: {', '.join(missing)}")
    for key in PLAN_SECTIONS:
        if not isinstance(raw[key], list) or not raw[key]:
            raise ValidationError(f"deployment plan {key} must be a non-empty list")
    return raw


def _serialize_release(release):
    return {
        "id": str(release.id),
        "project_id": str(release.project_id),
        "change_set_id": str(release.change_set_id),
        "version": release.version,
        "commit_sha": release.commit_sha,
        "release_notes": release.release_notes,
        "content_hash": release.content_hash,
        "status": release.status,
        "readiness": release.readiness,
        "readiness_checks": [_serialize_check(item) for item in release.readiness_checks],
        "package": release.package,
        "rollback": release.rollback,
        "created_by": release.created_by,
        "created_at": release.created_at.isoformat(),
    }


def _serialize_check(item):
    return {
        "key": item.key,
        "category": item.category,
        "mandatory": item.mandatory,
        "status": item.status,
        "detail": item.detail,
        "evidence": item.evidence,
    }


def _serialize_plan(plan, *, include_content=False):
    data = {
        "id": str(plan.id),
        "project_id": str(plan.project_id),
        "release_id": str(plan.release_id),
        "environment": plan.environment,
        "version": plan.version,
        "content_hash": plan.content_hash,
        "status": plan.status,
        "created_by": plan.created_by,
        "created_at": plan.created_at.isoformat(),
    }
    if include_content:
        data["content"] = plan.content
    return data


def _serialize_deployment(item):
    return {
        "id": str(item.id),
        "project_id": str(item.project_id),
        "release_id": str(item.release_id),
        "deployment_plan_id": str(item.deployment_plan_id),
        "environment": item.environment,
        "status": item.status,
        "provider": item.provider,
        "provider_id": item.provider_id,
        "diagnostics": item.diagnostics,
        "health_checks": item.health_checks,
        "rollback": item.rollback,
        "created_by": item.created_by,
        "created_at": item.created_at.isoformat(),
        "started_at": item.started_at.isoformat() if item.started_at else None,
        "finished_at": item.finished_at.isoformat() if item.finished_at else None,
    }


def _change_set(change_set_id):
    item = ChangeSet.query.filter_by(id=change_set_id, organization_id=_org().id).first()
    if item is None:
        raise NotFoundError("Change set not found")
    return item


def _get_release(release_id):
    item = Release.query.filter_by(id=release_id, organization_id=_org().id).first()
    if item is None:
        raise NotFoundError("Release not found")
    return item


def _get_plan(plan_id):
    item = DeploymentPlan.query.filter_by(id=plan_id, organization_id=_org().id).first()
    if item is None:
        raise NotFoundError("Deployment plan not found")
    return item


def _get_deployment(deployment_id):
    item = Deployment.query.filter_by(id=deployment_id, organization_id=_org().id).first()
    if item is None:
        raise NotFoundError("Deployment not found")
    return item


def _org():
    org = getattr(g, "organization", None)
    if org is None:
        raise AuthenticationError("Authenticated organization not found")
    return org


def _require(scope):
    from ..auth.roles import has_scope

    if g.user is None or not has_scope(g.user, scope):
        raise AuthenticationError(f"{scope} scope required")


def _uuid(value, field):
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValidationError(f"{field} must be a valid UUID") from exc


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _audit(action, target, metadata):
    record_audit(
        action=action,
        target_type=target.__class__.__name__.lower(),
        target_id=target.id,
        organization_id=target.organization_id,
        metadata=metadata,
    )
