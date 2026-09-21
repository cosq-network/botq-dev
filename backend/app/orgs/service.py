import re

from ..auth.roles import SYSTEM_ROLES, default_role_names
from ..errors import ConflictError
from ..extensions import db
from ..models import Organization, Role
from ..utils import new_uuid, validate_slug

_SLUG_RE = re.compile(r"[^a-z0-9_-]")


def slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", name.lower().strip())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug[:60]


def create_organization(name: str, slug: str | None = None) -> Organization:
    slug = slug or slugify(name)
    if not validate_slug(slug):
        raise ConflictError("Invalid organization slug", code="invalid_slug")
    if Organization.query.filter_by(slug=slug).first():
        raise ConflictError("Organization slug already exists", code="slug_taken")
    org = Organization(id=new_uuid(), name=name.strip(), slug=slug)
    db.session.add(org)
    db.session.flush()
    ensure_roles(org)
    db.session.commit()
    return org


def ensure_roles(org: Organization) -> dict[str, Role]:
    existing = {role.name: role for role in org.roles or []}
    created: dict[str, Role] = {}
    for name in default_role_names():
        if name not in existing:
            role = Role(
                id=new_uuid(),
                organization_id=org.id,
                name=name,
                scopes=SYSTEM_ROLES[name],
                is_system=True,
            )
            db.session.add(role)
            created[name] = role
        elif existing[name].is_system and existing[name].scopes != SYSTEM_ROLES[name]:
            # Keep existing organizations aligned with reviewed system-role capabilities
            # without overwriting organization-defined custom roles.
            existing[name].scopes = SYSTEM_ROLES[name]
    db.session.flush()
    return created


def get_org(org_id) -> Organization | None:
    return Organization.query.get(org_id)


def roles_for_org(org_id) -> dict[str, Role]:
    roles = Role.query.filter_by(organization_id=org_id).all()
    return {role.name: role for role in roles}
