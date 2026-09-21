import uuid

from flask import Blueprint, g, request

from ..api.responses import ok
from ..approvals.routes import _decide
from ..artifacts import service
from ..audit.service import record_audit
from ..errors import AuthenticationError, ConflictError, NotFoundError, ValidationError
from ..extensions import db
from ..models import (
    ArchitectureDecisionRecord,
    Artifact,
    ArtifactVersion,
    DesignComment,
    RequirementBaseline,
)
from ..utils import new_uuid, utcnow

bp = Blueprint("architecture", __name__, url_prefix="/architecture")

REQUIRED_SECTIONS = {
    "context",
    "components",
    "data",
    "integrations",
    "deployment",
    "security",
    "operations",
    "threats",
    "failures",
}


@bp.post("/packages")
def create_package():
    _require_write()
    org = _org()
    payload = request.get_json(silent=True) or {}
    title = _title(payload.get("title"))
    project_id = _uuid(payload.get("project_id"), "project_id")
    baseline_id = _uuid(payload.get("source_baseline_id"), "source_baseline_id")
    baseline = RequirementBaseline.query.filter_by(
        id=baseline_id, organization_id=org.id, project_id=project_id
    ).first()
    if baseline is None:
        raise NotFoundError("Approved requirement baseline not found")
    if baseline.status != "approved":
        raise ConflictError(
            "Architecture requires an approved requirement baseline", code="baseline_not_approved"
        )
    baseline_version = next(
        (version for version in baseline.versions if version.version == baseline.current_version),
        None,
    )
    if baseline_version is None:
        raise NotFoundError("Current requirement baseline version not found")
    content = service.normalize_content(payload.get("content"))
    missing = sorted(REQUIRED_SECTIONS - set(content))
    if missing:
        raise ValidationError(f"Architecture content is missing sections: {', '.join(missing)}")
    artifact, version = service.new_artifact(
        organization_id=org.id,
        project_id=project_id,
        artifact_type="architecture",
        title=title,
        content=content,
        created_by=str(g.user.id),
    )
    artifact.source_baseline_id = baseline.id
    artifact.source_baseline_version = baseline.current_version
    artifact.source_baseline_hash = baseline_version.content_hash
    db.session.add_all([artifact, version])
    db.session.commit()
    _audit("architecture.created", artifact, {"baseline_id": str(baseline.id)})
    return ok(_serialize(artifact, include_content=True), status=201)


@bp.get("/packages")
def list_packages():
    _require_read()
    query = Artifact.query.filter_by(organization_id=_org().id, artifact_type="architecture")
    project_id = request.args.get("project_id")
    if project_id:
        query = query.filter_by(project_id=_uuid(project_id, "project_id"))
    return ok([_serialize(item) for item in query.order_by(Artifact.created_at.desc()).all()])


@bp.get("/packages/<uuid:artifact_id>")
def get_package(artifact_id):
    _require_read()
    artifact = _get(artifact_id)
    return ok(_serialize(artifact, include_content=True))


@bp.post("/packages/<uuid:artifact_id>/versions")
def revise_package(artifact_id):
    _require_write()
    org = _org()
    artifact = _get(artifact_id)
    if artifact.status == "approved":
        # The new version is a fresh reviewable artifact state; the old approval
        # remains immutable history and cannot authorize this content.
        pass
    if artifact.status in {"cancelled"}:
        raise ConflictError(
            "Cancelled architecture cannot be revised", code="invalid_artifact_state"
        )
    content = service.normalize_content((request.get_json(silent=True) or {}).get("content"))
    missing = sorted(REQUIRED_SECTIONS - set(content))
    if missing:
        raise ValidationError(f"Architecture content is missing sections: {', '.join(missing)}")
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
        change_summary=(request.get_json(silent=True) or {}).get("change_summary")
        or "revised architecture",
        created_by=str(g.user.id),
    )
    artifact.current_version = version.version
    artifact.status = "draft"
    impacted_plans = (
        Artifact.query.filter_by(
            organization_id=org.id, source_artifact_id=artifact.id, artifact_type="technical_plan"
        )
        .filter(Artifact.status.in_(["submitted", "approved"]))
        .all()
    )
    for plan in impacted_plans:
        plan.status = "changes_requested"
    db.session.add(version)
    db.session.commit()
    _audit(
        "architecture.version_created",
        artifact,
        {
            "version": version.version,
            "impacted_plans": [str(plan.id) for plan in impacted_plans],
        },
    )
    return ok(_serialize(artifact, include_content=True), status=201)


@bp.post("/packages/<uuid:artifact_id>/submit")
def submit_package(artifact_id):
    _require_write()
    artifact = _get(artifact_id)
    if artifact.status not in service.SUBMITTABLE_STATUSES:
        raise ConflictError(
            "Architecture is not in a submittable state", code="invalid_artifact_state"
        )
    if any(comment.status == "open" for comment in artifact.comments):
        raise ConflictError(
            "Open design comments must be resolved before submission", code="open_design_comments"
        )
    artifact.status = "submitted"
    db.session.commit()
    _audit("architecture.submitted", artifact, {})
    return ok(_serialize(artifact, include_content=True))


@bp.post("/packages/<uuid:artifact_id>/approve")
def approve_package(artifact_id):
    return _review(artifact_id, "approved")


@bp.post("/packages/<uuid:artifact_id>/request-changes")
def request_changes_package(artifact_id):
    return _review(artifact_id, "changes_requested")


@bp.post("/packages/<uuid:artifact_id>/reject")
def reject_package(artifact_id):
    return _review(artifact_id, "rejected")


@bp.post("/packages/<uuid:artifact_id>/waive")
def waive_package(artifact_id):
    return _review(artifact_id, "waived")


@bp.post("/packages/<uuid:artifact_id>/adrs")
def create_adr(artifact_id):
    _require_write()
    org = _org()
    artifact = _get(artifact_id)
    if artifact.status not in {"draft", "changes_requested"}:
        raise ConflictError(
            "ADRs can only be added to a draft architecture", code="invalid_artifact_state"
        )
    payload = request.get_json(silent=True) or {}
    key = (payload.get("key") or "").strip().upper()
    if not key or len(key) > 32:
        raise ValidationError("key is required (max 32 characters)")
    required = ("title", "context", "decision", "consequences")
    if any(
        not isinstance(payload.get(field), str) or not payload[field].strip() for field in required
    ):
        raise ValidationError("title, context, decision and consequences are required")
    adr = ArchitectureDecisionRecord(
        id=new_uuid(),
        organization_id=org.id,
        project_id=artifact.project_id,
        artifact_id=artifact.id,
        artifact_version=artifact.current_version,
        key=key,
        title=payload["title"].strip()[:200],
        context=payload["context"].strip(),
        decision=payload["decision"].strip(),
        consequences=payload["consequences"].strip(),
        created_by=str(g.user.id),
    )
    db.session.add(adr)
    db.session.commit()
    _audit("architecture.adr_created", artifact, {"key": key})
    return ok(_serialize_adr(adr), status=201)


@bp.post("/packages/<uuid:artifact_id>/comments")
def add_comment(artifact_id):
    _require_write()
    org = _org()
    artifact = _get(artifact_id)
    payload = request.get_json(silent=True) or {}
    body = (payload.get("body") or "").strip()
    anchor = payload.get("anchor") or {}
    if not body or len(body) > 10000:
        raise ValidationError("body is required (max 10000 characters)")
    if not isinstance(anchor, dict):
        raise ValidationError("anchor must be an object")
    comment = DesignComment(
        id=new_uuid(),
        organization_id=org.id,
        project_id=artifact.project_id,
        artifact_id=artifact.id,
        artifact_version=int(payload.get("version", artifact.current_version)),
        anchor=anchor,
        body=body,
        created_by=str(g.user.id),
    )
    if comment.artifact_version < 1 or comment.artifact_version > artifact.current_version:
        raise ValidationError("version must reference an existing architecture version")
    db.session.add(comment)
    db.session.commit()
    _audit("architecture.comment_added", artifact, {"comment_id": str(comment.id)})
    return ok(_serialize_comment(comment), status=201)


@bp.post("/comments/<uuid:comment_id>/resolve")
def resolve_comment(comment_id):
    _require_write()
    comment = DesignComment.query.filter_by(id=comment_id, organization_id=_org().id).first()
    if comment is None:
        raise NotFoundError("Design comment not found")
    if comment.status != "open":
        raise ConflictError("Design comment is already resolved", code="comment_already_resolved")
    comment.status = "resolved"
    comment.resolved_by = str(g.user.id)
    comment.resolved_at = utcnow()
    db.session.commit()
    return ok(_serialize_comment(comment))


def _review(artifact_id, decision):
    payload = request.get_json(silent=True) or {}
    _decide("architecture", artifact_id, decision, payload)
    return ok(_serialize(_get(artifact_id), include_content=True))


def _get(artifact_id):
    artifact = Artifact.query.filter_by(
        id=artifact_id, organization_id=_org().id, artifact_type="architecture"
    ).first()
    if artifact is None:
        raise NotFoundError("Architecture package not found")
    return artifact


def _serialize(artifact, *, include_content=False):
    data = service.serialize_artifact(artifact, include_content=include_content)
    data["source_requirement"] = {
        "baseline_id": str(artifact.source_baseline_id),
        "version": artifact.source_baseline_version,
        "hash": artifact.source_baseline_hash,
    }
    data["adrs"] = [_serialize_adr(adr) for adr in artifact.decisions]
    data["comments"] = [_serialize_comment(comment) for comment in artifact.comments]
    return data


def _serialize_adr(adr):
    return {
        "id": str(adr.id),
        "artifact_id": str(adr.artifact_id),
        "version": adr.artifact_version,
        "key": adr.key,
        "title": adr.title,
        "context": adr.context,
        "decision": adr.decision,
        "consequences": adr.consequences,
        "status": adr.status,
        "created_by": adr.created_by,
        "created_at": adr.created_at.isoformat(),
    }


def _serialize_comment(comment):
    return {
        "id": str(comment.id),
        "artifact_id": str(comment.artifact_id),
        "version": comment.artifact_version,
        "anchor": comment.anchor,
        "body": comment.body,
        "status": comment.status,
        "created_by": comment.created_by,
        "resolved_by": comment.resolved_by,
        "created_at": comment.created_at.isoformat(),
    }


def _audit(action, artifact, metadata):
    record_audit(
        action=action,
        actor_id=str(g.user.id),
        target_type="architecture",
        target_id=artifact.id,
        organization_id=_org().id,
        metadata={"version": artifact.current_version, **metadata},
    )


def _title(value):
    title = (value or "").strip()
    if not title or len(title) > 200:
        raise ValidationError("title is required (max 200 characters)")
    return title


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


def _require_read():
    from ..auth.roles import has_scope

    if g.user is None or not has_scope(g.user, "design:read"):
        raise AuthenticationError("design:read scope required")


def _require_write():
    from ..auth.roles import has_scope

    if g.user is None or not has_scope(g.user, "design:write"):
        raise AuthenticationError("design:write scope required")
