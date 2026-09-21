import json
import uuid

from flask import Blueprint, g, request

from ..api.responses import ok
from ..audit.service import record_audit
from ..auth.roles import has_scope
from ..errors import AuthenticationError, ConflictError, NotFoundError, ValidationError
from ..extensions import db
from ..models import Artifact, Project, RequirementBaseline, TraceLink, WorkItem
from ..utils import new_uuid

bp = Blueprint("traceability", __name__, url_prefix="/traceability")
ENTITY_TYPES = {"requirement_baseline", "work_item", "architecture", "technical_plan", "mockup"}


@bp.post("/links")
def create_link():
    _require_read()
    payload = request.get_json(silent=True) or {}
    source_type = (payload.get("source_type") or "").strip()
    target_type = (payload.get("target_type") or "").strip()
    relation = (payload.get("relation") or "satisfies").strip()
    source_id = str(payload.get("source_id") or "")
    target_id = str(payload.get("target_id") or "")
    if source_type not in ENTITY_TYPES or target_type not in ENTITY_TYPES:
        raise ValidationError("source_type and target_type must be supported entity types")
    if not source_id or not target_id or not relation:
        raise ValidationError("source_id, target_id and relation are required")
    _ensure_entity(source_type, source_id)
    _ensure_entity(target_type, target_id)
    link = TraceLink(
        id=new_uuid(),
        organization_id=_org().id,
        project_id=_entity_project(source_type, source_id),
        source_type=source_type,
        source_id=source_id,
        target_type=target_type,
        target_id=target_id,
        relation=relation,
        created_by=str(g.user.id),
    )
    if _entity_project(target_type, target_id) != link.project_id:
        raise ValidationError("Trace links must stay within one project")
    if TraceLink.query.filter_by(
        project_id=link.project_id,
        source_type=source_type,
        source_id=source_id,
        target_type=target_type,
        target_id=target_id,
        relation=relation,
    ).first():
        raise ConflictError("Trace link already exists", code="duplicate_trace_link")
    db.session.add(link)
    db.session.commit()
    record_audit(
        action="trace_link.created",
        actor_id=str(g.user.id),
        target_type="trace_link",
        target_id=link.id,
        organization_id=_org().id,
        metadata={"source": source_id, "target": target_id, "relation": relation},
    )
    return ok(_serialize(link), status=201)


@bp.get("/links")
def list_links():
    _require_read()
    query = TraceLink.query.filter_by(organization_id=_org().id)
    for field in ("source_type", "source_id", "target_type", "target_id", "relation"):
        if request.args.get(field):
            query = query.filter_by(**{field: request.args[field]})
    return ok([_serialize(link) for link in query.order_by(TraceLink.created_at.asc()).all()])


@bp.delete("/links/<uuid:link_id>")
def delete_link(link_id):
    _require_write()
    link = TraceLink.query.filter_by(id=link_id, organization_id=_org().id).first()
    if link is None:
        raise NotFoundError("Trace link not found")
    db.session.delete(link)
    db.session.commit()
    return ok({"deleted": True, "id": str(link_id)})


@bp.get("/search")
def search():
    _require_read()
    term = (request.args.get("q") or "").strip().casefold()
    if len(term) < 2:
        raise ValidationError("q must contain at least two characters")
    results = []
    for project in Project.query.filter_by(organization_id=_org().id, archived=False).all():
        if _contains(term, project.name, project.key, project.description):
            results.append({"type": "project", "id": str(project.id), "title": project.name})
    for baseline in RequirementBaseline.query.filter_by(organization_id=_org().id).all():
        if _contains(
            term,
            baseline.title,
            baseline.project.name if baseline.project else "",
            baseline.versions[-1].content if baseline.versions else {},
        ):
            results.append(
                {"type": "requirement_baseline", "id": str(baseline.id), "title": baseline.title}
            )
    for item in WorkItem.query.filter_by(organization_id=_org().id).all():
        if _contains(term, item.code, item.title, item.description, item.acceptance_criteria):
            results.append(
                {"type": "work_item", "id": str(item.id), "title": item.title, "code": item.code}
            )
    for artifact in Artifact.query.filter_by(organization_id=_org().id).all():
        version = artifact.versions[-1] if artifact.versions else None
        if _contains(term, artifact.title, version.content if version else {}):
            results.append(
                {"type": artifact.artifact_type, "id": str(artifact.id), "title": artifact.title}
            )
    return ok(results[:100])


def _ensure_entity(entity_type, entity_id):
    try:
        parsed = uuid.UUID(entity_id)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValidationError(f"{entity_type} id must be a valid UUID") from exc
    if entity_type == "requirement_baseline":
        exists = RequirementBaseline.query.filter_by(id=parsed, organization_id=_org().id).first()
    elif entity_type == "work_item":
        exists = WorkItem.query.filter_by(id=parsed, organization_id=_org().id).first()
    else:
        exists = Artifact.query.filter_by(
            id=parsed, organization_id=_org().id, artifact_type=entity_type
        ).first()
    if exists is None:
        raise NotFoundError(f"{entity_type} not found")
    return exists


def _entity_project(entity_type, entity_id):
    return _ensure_entity(entity_type, entity_id).project_id


def _contains(term, *values):
    return term in json.dumps(values, ensure_ascii=False, default=str).casefold()


def _serialize(link):
    return {
        "id": str(link.id),
        "project_id": str(link.project_id),
        "source_type": link.source_type,
        "source_id": link.source_id,
        "target_type": link.target_type,
        "target_id": link.target_id,
        "relation": link.relation,
        "created_by": link.created_by,
        "created_at": link.created_at.isoformat(),
    }


def _org():
    org = getattr(g, "organization", None)
    if org is None:
        raise AuthenticationError("Authenticated organization not found")
    return org


def _require_read():
    if g.user is None or not (
        has_scope(g.user, "project:read")
        or has_scope(g.user, "requirement:read")
        or has_scope(g.user, "design:read")
        or has_scope(g.user, "plan:read")
    ):
        raise AuthenticationError("A read scope is required")


def _require_write():
    if g.user is None or not (
        has_scope(g.user, "requirement:write")
        or has_scope(g.user, "design:write")
        or has_scope(g.user, "plan:write")
    ):
        raise AuthenticationError("A workflow write scope is required")
