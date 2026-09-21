import uuid

from flask import Blueprint, g, request

from ..api.responses import ok
from ..audit.service import record_audit
from ..errors import AuthenticationError, ConflictError, NotFoundError, ValidationError
from ..extensions import db
from ..models import Project, WorkItem
from . import service

bp = Blueprint("work_items", __name__, url_prefix="/work-items")


def _parse_uuid(value, field):
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

    user = getattr(g, "user", None)
    if user is None or not has_scope(user, "requirement:read"):
        raise AuthenticationError("requirement:read scope required")


def _require_write():
    from ..auth.roles import has_scope

    user = getattr(g, "user", None)
    if user is None or not has_scope(user, "requirement:write"):
        raise AuthenticationError("requirement:write scope required")


def _owned_project(project_id) -> Project:
    project = Project.query.filter_by(
        id=_parse_uuid(project_id, "project_id"), organization_id=_org().id
    ).first()
    if project is None:
        raise NotFoundError("Project not found")
    return project


def _clean_str_list(raw, field):
    if raw is None:
        return []
    if not isinstance(raw, list) or any(not isinstance(x, str) for x in raw):
        raise ValidationError(f"{field} must be a list of strings")
    return [x.strip() for x in raw if x.strip()]


@bp.post("")
def create_work_item():
    _require_write()
    org = _org()
    payload = request.get_json(silent=True) or {}
    project = _owned_project(payload.get("project_id"))

    kind = service.validate_enum((payload.get("kind") or "").strip().lower(), service.KINDS, "kind")
    title = (payload.get("title") or "").strip()
    if not title or len(title) > 200:
        raise ValidationError("title is required (max 200 characters)")

    parent = None
    if payload.get("parent_id"):
        parent = service.get_owned_work_item(_parse_uuid(payload["parent_id"], "parent_id"), org.id)
        if str(parent.project_id) != str(project.id):
            raise ValidationError("parent must belong to the same project")
    service.validate_parent(kind, parent)

    priority = service.validate_enum(
        (payload.get("priority") or "medium").strip().lower(), service.PRIORITIES, "priority"
    )
    risk = service.validate_enum(
        (payload.get("risk") or "low").strip().lower(), service.RISKS, "risk"
    )
    status = service.validate_enum(
        (payload.get("status") or "draft").strip().lower(), service.STATUSES, "status"
    )
    source_baseline_id = (
        _parse_uuid(payload["source_baseline_id"], "source_baseline_id")
        if payload.get("source_baseline_id")
        else None
    )
    is_derived = bool(payload.get("is_derived", False))
    service.validate_traceability(source_baseline_id, is_derived, org.id, project.id)

    number = service.next_number(project.id)
    code = f"{project.key.upper()}-{number}"
    item = service.new_work_item(
        organization_id=org.id,
        project_id=project.id,
        code=code,
        number=number,
        kind=kind,
        parent_id=parent.id if parent else None,
        title=title,
        description=payload.get("description"),
        acceptance_criteria=_clean_str_list(
            payload.get("acceptance_criteria"), "acceptance_criteria"
        ),
        priority=priority,
        risk=risk,
        status=status,
        owner_id=payload.get("owner_id"),
        release_target=payload.get("release_target"),
        estimate=payload.get("estimate"),
        source_baseline_id=source_baseline_id,
        source_refs=_clean_str_list(payload.get("source_refs"), "source_refs"),
        is_derived=is_derived,
        created_by=str(g.user.id),
    )
    db.session.add(item)
    db.session.commit()
    record_audit(
        action="work_item.created",
        actor_id=str(g.user.id),
        target_type="work_item",
        target_id=item.id,
        organization_id=org.id,
        metadata={"code": code, "kind": kind, "project_id": str(project.id)},
    )
    return ok(service.serialize(item), status=201)


@bp.get("")
def list_work_items():
    _require_read()
    org = _org()
    project_id = request.args.get("project_id")
    if not project_id:
        raise ValidationError("project_id query parameter is required")
    project = _owned_project(project_id)
    query = WorkItem.query.filter_by(organization_id=org.id, project_id=project.id)
    if request.args.get("kind"):
        query = query.filter_by(kind=request.args["kind"])
    if request.args.get("status"):
        query = query.filter_by(status=request.args["status"])
    items = query.order_by(WorkItem.number.asc()).all()
    return ok([service.serialize(i) for i in items])


@bp.get("/tree")
def work_item_tree():
    _require_read()
    org = _org()
    project = _owned_project(request.args.get("project_id"))
    items = WorkItem.query.filter_by(organization_id=org.id, project_id=project.id).all()
    return ok(service.build_tree(items))


@bp.get("/<uuid:work_item_id>")
def get_work_item(work_item_id):
    _require_read()
    item = service.get_owned_work_item(work_item_id, _org().id)
    return ok(service.serialize(item, include_children=True))


@bp.patch("/<uuid:work_item_id>")
def update_work_item(work_item_id):
    _require_write()
    org = _org()
    item = service.get_owned_work_item(work_item_id, org.id)
    payload = request.get_json(silent=True) or {}

    if "kind" in payload:
        kind = service.validate_enum((payload["kind"] or "").strip().lower(), service.KINDS, "kind")
    else:
        kind = item.kind

    parent_id = payload["parent_id"] if "parent_id" in payload else item.parent_id
    if parent_id:
        parent = service.get_owned_work_item(_parse_uuid(parent_id, "parent_id"), org.id)
        if str(parent.project_id) != str(item.project_id):
            raise ValidationError("parent must belong to the same project")
    else:
        parent = None

    # Detect a parent-adjacency cycle before shape validation so reparenting under a
    # descendant reports the accurate circular-hierarchy error.
    if parent is not None and (parent.id == item.id or parent.id in service._descendants(item)):
        raise ConflictError(
            "Reparenting would create a circular hierarchy",
            code="circular_hierarchy",
        )
    service.validate_parent(kind, parent)

    item.kind = kind
    item.parent_id = parent.id if parent else None

    if "title" in payload and payload["title"]:
        item.title = payload["title"].strip()[:200]
    if "description" in payload:
        item.description = payload["description"]
    if "acceptance_criteria" in payload:
        item.acceptance_criteria = _clean_str_list(
            payload["acceptance_criteria"], "acceptance_criteria"
        )
    if "priority" in payload:
        item.priority = service.validate_enum(
            (payload["priority"] or "").strip().lower(), service.PRIORITIES, "priority"
        )
    if "risk" in payload:
        item.risk = service.validate_enum(
            (payload["risk"] or "").strip().lower(), service.RISKS, "risk"
        )
    if "status" in payload:
        item.status = service.validate_enum(
            (payload["status"] or "").strip().lower(), service.STATUSES, "status"
        )
    for field in ("owner_id", "release_target", "estimate"):
        if field in payload:
            setattr(item, field, payload[field])

    db.session.commit()
    record_audit(
        action="work_item.updated",
        actor_id=str(g.user.id),
        target_type="work_item",
        target_id=item.id,
        organization_id=org.id,
        metadata={"code": item.code, "changes": sorted(payload.keys())},
    )
    return ok(service.serialize(item))


@bp.delete("/<uuid:work_item_id>")
def delete_work_item(work_item_id):
    _require_write()
    org = _org()
    item = service.get_owned_work_item(work_item_id, org.id)
    if item.children:
        raise ConflictError(
            "Work item has children; reassign or delete them first",
            code="work_item_has_children",
        )
    code = item.code
    db.session.delete(item)
    db.session.commit()
    record_audit(
        action="work_item.deleted",
        actor_id=str(g.user.id),
        target_type="work_item",
        target_id=work_item_id,
        organization_id=org.id,
        metadata={"code": code},
    )
    return ok({"deleted": True, "code": code})


@bp.get("/<uuid:work_item_id>/dependencies")
def list_dependencies(work_item_id):
    _require_read()
    item = service.get_owned_work_item(work_item_id, _org().id)
    return ok(
        {
            "depends_on": [service.serialize(d) for d in item.dependencies],
            "blocks": [service.serialize(d) for d in item.dependents],
        }
    )


@bp.post("/<uuid:work_item_id>/dependencies")
def add_dependency(work_item_id):
    _require_write()
    org = _org()
    item = service.get_owned_work_item(work_item_id, org.id)
    payload = request.get_json(silent=True) or {}
    target = service.get_owned_work_item(
        _parse_uuid(payload.get("depends_on_id"), "depends_on_id"), org.id
    )
    service.add_dependency(item, target)
    record_audit(
        action="work_item.dependency_added",
        actor_id=str(g.user.id),
        target_type="work_item",
        target_id=item.id,
        organization_id=org.id,
        metadata={"code": item.code, "depends_on": target.code},
    )
    return ok(service.serialize(item))


@bp.delete("/<uuid:work_item_id>/dependencies/<uuid:depends_on_id>")
def remove_dependency(work_item_id, depends_on_id):
    _require_write()
    org = _org()
    item = service.get_owned_work_item(work_item_id, org.id)
    target = service.get_owned_work_item(depends_on_id, org.id)
    if target not in item.dependencies:
        raise NotFoundError("Dependency not found")
    item.dependencies.remove(target)
    db.session.commit()
    record_audit(
        action="work_item.dependency_removed",
        actor_id=str(g.user.id),
        target_type="work_item",
        target_id=item.id,
        organization_id=org.id,
        metadata={"code": item.code, "depends_on": target.code},
    )
    return ok(service.serialize(item))
