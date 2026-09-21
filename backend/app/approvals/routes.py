import uuid
from datetime import datetime

from flask import Blueprint, g, request

from ..api.responses import ok
from ..audit.service import record_audit
from ..errors import AuthenticationError, AuthorizationError, ValidationError
from ..models import ProjectResponsibilityAssignment
from ..utils import utcnow
from .service import REVIEW_DECISIONS, decide, resolve_artifact, serialize

bp = Blueprint("approvals", __name__, url_prefix="/approvals")


def _parse_expires(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as exc:
        raise ValidationError("expires_at must be an ISO-8601 timestamp") from exc


def _org_id():
    org = getattr(g, "organization", None)
    if org is None:
        raise AuthenticationError("Authenticated organization not found")
    return org.id


def _decide(artifact_type, artifact_id, decision, payload):
    user = getattr(g, "user", None)
    if user is None:
        raise AuthenticationError("Authentication required")
    if decision in REVIEW_DECISIONS:
        from ..auth.roles import has_scope

        if not has_scope(user, "approval"):
            raise AuthenticationError("approval scope required")
    elif decision == "cancelled":
        from ..auth.roles import has_scope

        if not (has_scope(user, "approval") or has_scope(user, "requirement:write")):
            raise AuthenticationError("approval or requirement:write scope required")
    try:
        artifact_uuid = (
            artifact_id if isinstance(artifact_id, uuid.UUID) else uuid.UUID(str(artifact_id))
        )
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValidationError("artifact_id must be a valid UUID") from exc
    org_id = _org_id()
    _require_project_responsibility(artifact_type, artifact_uuid, org_id, user.id)
    approval, info = decide(
        artifact_type=artifact_type,
        artifact_id=artifact_uuid,
        decision=decision,
        org_id=org_id,
        decider_id=str(user.id),
        decider_roles=sorted(role.name for role in user.roles),
        version=payload.get("version"),
        content_hash=payload.get("content_hash") or payload.get("hash"),
        reason=payload.get("reason"),
        expires_at=_parse_expires(payload.get("expires_at")),
    )
    record_audit(
        action="approval.decided",
        actor_id=str(user.id),
        target_type=artifact_type,
        target_id=approval.id,
        organization_id=org_id,
        metadata={
            "artifact_type": approval.artifact_type,
            "artifact_id": approval.artifact_id,
            "decision": approval.decision,
            "version": approval.artifact_version,
            "content_hash": approval.artifact_hash,
        },
    )
    return approval


PROJECT_REVIEW_RESPONSIBILITIES = {
    "requirement_baseline": "product_owner",
    "architecture": "architecture_reviewer",
    "technical_plan": "architecture_reviewer",
    "mockup": "designer",
    "change_set": "qa_reviewer",
    "release": "release_manager",
    "deployment_plan": "operations_approver",
}


def _require_project_responsibility(artifact_type, artifact_id, org_id, user_id):
    """Enforce project assignment only when the organization opts into it."""
    org = getattr(g, "organization", None)
    if not org or not (org.settings or {}).get("enforce_project_responsibilities"):
        return
    responsibility_type = PROJECT_REVIEW_RESPONSIBILITIES.get(artifact_type)
    if responsibility_type is None:
        return
    info = resolve_artifact(artifact_type, artifact_id, org_id)
    now = utcnow()
    assigned = ProjectResponsibilityAssignment.query.filter(
        ProjectResponsibilityAssignment.organization_id == org_id,
        ProjectResponsibilityAssignment.project_id == info["project_id"],
        ProjectResponsibilityAssignment.user_id == user_id,
        ProjectResponsibilityAssignment.responsibility_type == responsibility_type,
        ProjectResponsibilityAssignment.is_primary.is_(True),
        ProjectResponsibilityAssignment.effective_from <= now,
        (ProjectResponsibilityAssignment.effective_until.is_(None))
        | (ProjectResponsibilityAssignment.effective_until > now),
    ).first()
    if assigned is None:
        raise AuthorizationError(
            f"The current user is not the active primary {responsibility_type} for this project"
        )


@bp.post("")
def create_approval():
    payload = request.get_json(silent=True) or {}
    artifact_type = (payload.get("artifact_type") or "").strip()
    artifact_id = payload.get("artifact_id")
    decision = (payload.get("decision") or "").strip()
    if not artifact_type or not artifact_id:
        raise ValidationError("artifact_type and artifact_id are required")
    if decision not in {"approved", "rejected", "changes_requested", "waived", "cancelled"}:
        raise ValidationError(f"Unknown decision '{decision}'")
    approval = _decide(artifact_type, artifact_id, decision, payload)
    return ok(serialize(approval), status=201)


@bp.get("")
def list_approvals():
    from ..models import Approval

    user = getattr(g, "user", None)
    if user is None:
        raise AuthenticationError("Authentication required")
    org = _org_id()
    query = Approval.query.filter_by(organization_id=org)
    artifact_type = request.args.get("artifact_type")
    artifact_id = request.args.get("artifact_id")
    if artifact_type:
        query = query.filter_by(artifact_type=artifact_type)
    if artifact_id:
        query = query.filter_by(artifact_id=str(artifact_id))
    approvals = query.order_by(Approval.created_at.desc()).all()
    return ok([serialize(a) for a in approvals])


@bp.get("/artifact/<artifact_type>/<uuid:artifact_id>")
def artifact_state(artifact_type, artifact_id):
    """Current version + hash an approval must bind to, plus its decision history."""
    from ..models import Approval

    info = resolve_artifact(artifact_type, artifact_id, _org_id())
    history = (
        Approval.query.filter_by(
            organization_id=_org_id(), artifact_type=artifact_type, artifact_id=info["id"]
        )
        .order_by(Approval.created_at.desc())
        .all()
    )
    return ok(
        {
            "artifact_type": info["type"],
            "artifact_id": info["id"],
            "version": info["version"],
            "content_hash": info["content_hash"],
            "status": info["status"],
            "author_id": info["author_id"],
            "approvals": [serialize(a) for a in history],
        }
    )
