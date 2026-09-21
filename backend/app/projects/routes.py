from datetime import datetime
from uuid import UUID

from flask import Blueprint, g, request

from ..api.responses import ok
from ..audit.service import record_audit
from ..auth.decorators import require_scope
from ..errors import ConflictError, NotFoundError, ValidationError
from ..extensions import db
from ..models import Organization, Project, ProjectResponsibilityAssignment, User
from ..utils import new_uuid, utcnow, validate_name, validate_slug

bp = Blueprint("projects", __name__, url_prefix="/projects")

RESPONSIBILITY_TYPES = {
    "product_owner",
    "architecture_reviewer",
    "developer",
    "qa_reviewer",
    "designer",
    "release_manager",
    "security_approver",
    "operations_approver",
}
DEFAULT_SEGREGATION_GROUPS = {
    "developer": "implementation_quality",
    "qa_reviewer": "implementation_quality",
    "release_manager": "release_security",
    "security_approver": "release_security",
}


def _serialize(project: Project) -> dict:
    repo = project.repository
    return {
        "id": str(project.id),
        "name": project.name,
        "key": project.key,
        "description": project.description,
        "lifecycle_state": project.lifecycle_state,
        "default_branch": project.default_branch,
        "archived": project.archived,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
        "repository": _serialize_repo(repo) if repo else None,
    }


def _serialize_repo(repo) -> dict:
    return {
        "id": str(repo.id),
        "ssh_url": repo.ssh_url,
        "host": repo.host,
        "host_fingerprint_verified": bool(repo.host_fingerprint),
        "scope": repo.scope,
        "default_branch": repo.default_branch,
        "status": repo.status,
        "deploy_key_public": repo.deploy_key_public,
        "last_sync_at": repo.last_sync_at.isoformat() if repo.last_sync_at else None,
        "last_error": repo.last_error,
    }


@bp.get("")
@require_scope("project:read")
def list_projects():
    org = _org()
    projects = Project.query.filter_by(organization_id=org.id, archived=False).all()
    return ok([_serialize(p) for p in projects])


@bp.post("")
@require_scope("project:write")
def create_project():
    org = _org()
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    key = (payload.get("key") or "").strip().lower()
    if not validate_name(name):
        raise ValidationError("Project name is required")
    if not validate_slug(key):
        raise ValidationError("Project key must be 2-64 lowercase alphanumeric with - or _")
    if Project.query.filter_by(organization_id=org.id, key=key).first():
        raise ConflictError("Project key already in use", code="duplicate_project_key")
    project = Project(
        id=new_uuid(),
        organization_id=org.id,
        name=name,
        key=key,
        description=payload.get("description"),
        default_branch=(payload.get("default_branch") or "main").strip() or "main",
        lifecycle_state=payload.get("lifecycle_state") or "requirements",
    )
    db.session.add(project)
    db.session.commit()
    record_audit(
        action="project.created",
        actor_id=str(g.user.id),
        target_type="project",
        target_id=project.id,
        organization_id=org.id,
        metadata={"name": project.name, "key": project.key},
    )
    return ok(_serialize(project), status=201)


@bp.get("/<uuid:project_id>")
@require_scope("project:read")
def get_project(project_id):
    project = _get_owned(project_id)
    return ok(_serialize(project))


@bp.patch("/<uuid:project_id>")
@require_scope("project:write")
def update_project(project_id):
    org = _org()
    project = _get_owned(project_id)
    payload = request.get_json(silent=True) or {}
    if "name" in payload and payload["name"]:
        project.name = payload["name"].strip()
    if "description" in payload:
        project.description = payload["description"]
    if "lifecycle_state" in payload:
        project.lifecycle_state = payload["lifecycle_state"]
    if "default_branch" in payload and payload["default_branch"]:
        project.default_branch = payload["default_branch"].strip()
    db.session.commit()
    record_audit(
        action="project.updated",
        actor_id=str(g.user.id),
        target_type="project",
        target_id=project.id,
        organization_id=org.id,
        metadata={"changes": sorted(set(payload.keys()))},
    )
    return ok(_serialize(project))


@bp.post("/<uuid:project_id>/archive")
@require_scope("project:write")
def archive_project(project_id):
    org = _org()
    project = _get_owned(project_id)
    project.archived = True
    db.session.commit()
    record_audit(
        action="project.archived",
        actor_id=str(g.user.id),
        target_type="project",
        target_id=project.id,
        organization_id=org.id,
    )
    return ok(_serialize(project))


@bp.get("/<uuid:project_id>/responsibility-assignments")
@require_scope("config:read")
def list_responsibility_assignments(project_id):
    project = _get_owned(project_id)
    query = ProjectResponsibilityAssignment.query.filter_by(project_id=project.id)
    if request.args.get("as_of"):
        as_of = _parse_datetime(request.args["as_of"], "as_of")
        query = query.filter(
            ProjectResponsibilityAssignment.effective_from <= as_of,
            (ProjectResponsibilityAssignment.effective_until.is_(None))
            | (ProjectResponsibilityAssignment.effective_until > as_of),
        )
    assignments = query.order_by(
        ProjectResponsibilityAssignment.responsibility_type.asc(),
        ProjectResponsibilityAssignment.is_primary.desc(),
        ProjectResponsibilityAssignment.effective_from.asc(),
    ).all()
    return ok([_serialize_assignment(item) for item in assignments])


@bp.post("/<uuid:project_id>/responsibility-assignments")
@require_scope("config:manage")
def create_responsibility_assignment(project_id):
    project = _get_owned(project_id)
    if project.archived:
        raise ConflictError("Cannot assign responsibilities to an archived project")
    payload = request.get_json(silent=True) or {}
    responsibility_type = _responsibility_type(payload)
    user = _org_user(payload.get("user_id"))
    effective_from = _parse_datetime(payload.get("effective_from"), "effective_from", default=utcnow())
    effective_until = _parse_optional_datetime(payload.get("effective_until"), "effective_until")
    if effective_until and effective_until <= effective_from:
        raise ValidationError("effective_until must be after effective_from")
    is_primary = payload.get("is_primary", True) is not False
    segregation_group = _segregation_group(responsibility_type, payload.get("segregation_group"))
    _validate_assignment_conflicts(
        project, responsibility_type, user, is_primary, segregation_group, effective_from, effective_until
    )
    assignment = ProjectResponsibilityAssignment(
        organization_id=project.organization_id,
        project_id=project.id,
        user_id=user.id,
        responsibility_type=responsibility_type,
        is_primary=is_primary,
        segregation_group=segregation_group,
        effective_from=effective_from,
        effective_until=effective_until,
        assigned_by=g.user.id,
    )
    db.session.add(assignment)
    db.session.commit()
    record_audit(
        action="project.responsibility_assigned",
        actor_id=str(g.user.id),
        target_type="project_responsibility_assignment",
        target_id=assignment.id,
        organization_id=project.organization_id,
        metadata={
            "project_id": str(project.id),
            "user_id": str(user.id),
            "responsibility_type": responsibility_type,
            "is_primary": is_primary,
        },
    )
    return ok(_serialize_assignment(assignment), status=201)


@bp.patch("/<uuid:project_id>/responsibility-assignments/<uuid:assignment_id>")
@require_scope("config:manage")
def update_responsibility_assignment(project_id, assignment_id):
    project = _get_owned(project_id)
    if project.archived:
        raise ConflictError("Cannot update responsibilities on an archived project")
    assignment = ProjectResponsibilityAssignment.query.filter_by(
        id=assignment_id, project_id=project.id, organization_id=project.organization_id
    ).first()
    if assignment is None:
        raise NotFoundError("Responsibility assignment not found")
    payload = request.get_json(silent=True) or {}
    responsibility_type = _responsibility_type(payload, assignment.responsibility_type)
    user = _org_user(payload.get("user_id", assignment.user_id))
    effective_from = _parse_datetime(
        payload.get("effective_from", assignment.effective_from.isoformat()), "effective_from"
    )
    effective_until = _parse_optional_datetime(
        payload.get("effective_until", assignment.effective_until.isoformat() if assignment.effective_until else None),
        "effective_until",
    )
    if effective_until and effective_until <= effective_from:
        raise ValidationError("effective_until must be after effective_from")
    is_primary = payload.get("is_primary", assignment.is_primary) is not False
    segregation_group = _segregation_group(
        responsibility_type, payload.get("segregation_group", assignment.segregation_group)
    )
    _validate_assignment_conflicts(
        project, responsibility_type, user, is_primary, segregation_group, effective_from, effective_until,
        exclude_id=assignment.id,
    )
    assignment.user_id = user.id
    assignment.responsibility_type = responsibility_type
    assignment.is_primary = is_primary
    assignment.segregation_group = segregation_group
    assignment.effective_from = effective_from
    assignment.effective_until = effective_until
    db.session.commit()
    record_audit(
        action="project.responsibility_updated",
        actor_id=str(g.user.id),
        target_type="project_responsibility_assignment",
        target_id=assignment.id,
        organization_id=project.organization_id,
        metadata={"project_id": str(project.id), "changes": sorted(payload.keys())},
    )
    return ok(_serialize_assignment(assignment))


def _org() -> Organization:
    org = getattr(g, "organization", None)
    if org is None:
        raise NotFoundError("Authenticated organization not found")
    return org


def _get_owned(project_id) -> Project:
    org = _org()
    project = Project.query.filter_by(id=project_id, organization_id=org.id).first()
    if project is None:
        raise NotFoundError("Project not found")
    return project


def _serialize_assignment(item):
    return {
        "id": str(item.id),
        "project_id": str(item.project_id),
        "user_id": str(item.user_id),
        "user": {"email": item.user.email, "display_name": item.user.display_name},
        "responsibility_type": item.responsibility_type,
        "is_primary": item.is_primary,
        "segregation_group": item.segregation_group,
        "effective_from": item.effective_from.isoformat(),
        "effective_until": item.effective_until.isoformat() if item.effective_until else None,
        "assigned_by": str(item.assigned_by) if item.assigned_by else None,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def _responsibility_type(payload, current=None):
    value = str(payload.get("responsibility_type", current) or "").strip().lower()
    if value not in RESPONSIBILITY_TYPES:
        raise ValidationError(
            "responsibility_type must be one of: " + ", ".join(sorted(RESPONSIBILITY_TYPES))
        )
    return value


def _org_user(value):
    try:
        user_id = UUID(str(value))
        user = User.query.filter_by(id=user_id, organization_id=g.organization.id, is_active=True).first()
    except (TypeError, ValueError, AttributeError):
        user = None
    if user is None:
        raise ValidationError("user_id must identify an active user in this organization")
    return user


def _parse_datetime(value, field, default=None):
    if not value:
        if default is not None:
            return default
        raise ValidationError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{field} must be an ISO-8601 datetime") from exc
    return parsed.replace(tzinfo=None)


def _parse_optional_datetime(value, field):
    return _parse_datetime(value, field) if value else None


def _segregation_group(responsibility_type, value):
    if value is None:
        return DEFAULT_SEGREGATION_GROUPS.get(responsibility_type)
    group = str(value).strip().lower()
    if len(group) > 64 or not group:
        raise ValidationError("segregation_group must be a non-empty value of at most 64 characters")
    return group


def _validate_assignment_conflicts(
    project, responsibility_type, user, is_primary, segregation_group, effective_from, effective_until, exclude_id=None
):
    query = ProjectResponsibilityAssignment.query.filter_by(project_id=project.id)
    if exclude_id:
        query = query.filter(ProjectResponsibilityAssignment.id != exclude_id)
    for existing in query.all():
        overlaps = existing.effective_from < (effective_until or datetime.max) and (
            existing.effective_until is None or effective_from < existing.effective_until
        )
        if not overlaps:
            continue
        if existing.responsibility_type == responsibility_type and existing.user_id == user.id:
            raise ConflictError("The user already has this overlapping project responsibility")
        if is_primary and existing.is_primary and existing.responsibility_type == responsibility_type:
            raise ConflictError("A project responsibility type can have only one overlapping primary user")
        if is_primary and existing.is_primary and segregation_group and existing.segregation_group == segregation_group and existing.user_id == user.id:
            raise ConflictError("Segregation-of-duties rule requires distinct users for this responsibility group")
