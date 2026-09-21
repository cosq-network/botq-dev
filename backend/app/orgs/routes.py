import hmac
from uuid import UUID

from flask import Blueprint, current_app, g, request
from werkzeug.security import generate_password_hash

from ..api.responses import ok
from ..audit.service import record_audit
from ..auth.decorators import require_auth, require_scope
from ..auth.roles import is_known_role
from ..errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from ..extensions import db
from ..models import Organization, Role, User
from ..orgs.service import create_organization, ensure_roles, roles_for_org
from ..utils import new_uuid

bp = Blueprint("orgs", __name__)

GATE_POLICY_DEFAULTS = {
    "approval_mode": "human_api",
    "require_gate_decisions": True,
    "require_project_responsibility_assignment": True,
    "allow_waivers": True,
    "require_previous_gate_closed": True,
    "auto_sync_evidence": True,
}
APPROVAL_MODES = {"human_api", "api_automation", "disabled"}


@bp.post("/organizations")
def create_org():
    if not current_app.config.get("BOOTSTRAP_ENABLED", False):
        raise AuthorizationError("Organization bootstrap is disabled")
    token = request.headers.get("X-Bootstrap-Token", "")
    expected = current_app.config.get("BOOTSTRAP_TOKEN", "")
    if not expected or not hmac.compare_digest(token, expected):
        raise AuthorizationError("Invalid bootstrap token")
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        from ..errors import ValidationError

        raise ValidationError("Organization name is required")
    org = create_organization(name, payload.get("slug"))
    record_audit(
        action="organization.created",
        actor_type="system",
        actor_id="bootstrap",
        target_type="organization",
        target_id=org.id,
        organization_id=None,
        metadata={"name": org.name},
    )
    return ok(
        {
            "id": str(org.id),
            "name": org.name,
            "slug": org.slug,
            "roles": [role.name for role in org.roles],
        },
        status=201,
    )


@bp.get("/organizations")
def list_orgs():
    if not current_app.config.get("BOOTSTRAP_ENABLED", False):
        raise AuthorizationError("Organization bootstrap is disabled")
    token = request.headers.get("X-Bootstrap-Token", "")
    expected = current_app.config.get("BOOTSTRAP_TOKEN", "")
    if not expected or not hmac.compare_digest(token, expected):
        raise AuthorizationError("Invalid bootstrap token")
    orgs = Organization.query.order_by(Organization.name.asc()).all()
    return ok(
        [
            {
                "id": str(o.id),
                "name": o.name,
                "slug": o.slug,
                "is_active": o.is_active,
            }
            for o in orgs
        ]
    )


@bp.get("/organizations/me")
@require_auth
def get_org_me():
    org = _current_org()
    return ok(
        {
            "id": str(org.id),
            "name": org.name,
            "slug": org.slug,
            "settings": org.settings or {},
        }
    )


@bp.patch("/organizations/me/settings")
@require_auth
@require_scope("config:manage")
def update_org_settings():
    """Update governed organization settings through an authorized client."""
    org = _current_org()
    payload = request.get_json(silent=True) or {}
    allowed = {"enforce_project_responsibilities"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValidationError(f"Unsupported organization setting(s): {', '.join(unknown)}")
    if "enforce_project_responsibilities" in payload and not isinstance(
        payload["enforce_project_responsibilities"], bool
    ):
        raise ValidationError("enforce_project_responsibilities must be boolean")
    org.settings = {**(org.settings or {}), **payload}
    db.session.commit()
    record_audit(
        action="organization.settings_updated",
        actor_id=str(g.user.id),
        target_type="organization",
        target_id=org.id,
        organization_id=org.id,
        metadata={"changes": sorted(payload.keys())},
    )
    return ok({"id": str(org.id), "settings": org.settings})


@bp.get("/organizations/me/gate-policy")
@require_auth
@require_scope("config:read")
def get_org_gate_policy():
    org = _current_org()
    return ok(_effective_gate_policy(org.settings or {}))


@bp.patch("/organizations/me/gate-policy")
@require_auth
@require_scope("config:manage")
def update_org_gate_policy():
    org = _current_org()
    policy = _validate_gate_policy(request.get_json(silent=True) or {}, partial=True)
    settings = dict(org.settings or {})
    current = _effective_gate_policy(settings)
    current.update(policy)
    current["version"] = _next_policy_version(current.get("version"))
    settings["gate_policy"] = current
    settings["enforce_project_responsibilities"] = current["require_project_responsibility_assignment"]
    org.settings = settings
    db.session.commit()
    record_audit(
        action="organization.gate_policy_updated",
        actor_id=str(g.user.id),
        target_type="organization",
        target_id=org.id,
        organization_id=org.id,
        metadata={"changes": sorted(policy.keys()), "version": current["version"]},
    )
    return ok(current)


@bp.get("/organizations/me/roles")
@require_auth
def list_org_roles():
    roles = roles_for_org(_current_org().id)
    return ok(
        [
            {"name": name, "scopes": role.scopes or [], "is_system": role.is_system}
            for name, role in sorted(roles.items())
        ]
    )


@bp.get("/organizations/me/users")
@require_auth
@require_scope("config:read")
def list_org_users():
    org = _current_org()
    users = User.query.filter_by(organization_id=org.id).all()
    return ok(
        [
            {
                "id": str(u.id),
                "email": u.email,
                "display_name": u.display_name,
                "roles": [role.name for role in u.roles],
                "is_active": u.is_active,
                "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            }
            for u in users
        ]
    )


@bp.post("/organizations/me/users")
@require_auth
@require_scope("config:manage")
def create_org_user():
    """Create an organization member through an authorized administration client."""
    org = _current_org()
    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    display_name = (payload.get("display_name") or "").strip()
    password = payload.get("password")
    user_type = str(payload.get("user_type") or payload.get("type") or "human").strip().lower()
    if not email or "@" not in email or len(email) > 254:
        raise ValidationError("email must be a valid email address")
    if not display_name or len(display_name) > 120:
        raise ValidationError("display_name is required (max 120 characters)")
    if user_type not in {"human", "automation"}:
        raise ValidationError("user_type must be human or automation")
    if user_type == "human" and (not isinstance(password, str) or len(password) < 12):
        raise ValidationError("password must be at least 12 characters")
    if user_type == "automation" and password is not None and (
        not isinstance(password, str) or len(password) < 12
    ):
        raise ValidationError("password must be at least 12 characters")
    if User.query.filter_by(organization_id=org.id, email=email).first():
        raise ConflictError("A user with this email already exists", code="duplicate_user_email")
    roles = _resolve_roles(org, payload.get("roles"))
    user = User(
        id=new_uuid(),
        organization_id=org.id,
        email=email,
        display_name=display_name,
        password_hash=generate_password_hash(password) if password else None,
        external_provider="automation" if user_type == "automation" else None,
        is_active=True,
    )
    user.roles = roles
    db.session.add(user)
    db.session.commit()
    record_audit(
        action="organization.user_created",
        actor_id=str(g.user.id),
        target_type="user",
        target_id=user.id,
        organization_id=org.id,
        metadata={"email": user.email, "roles": [role.name for role in roles], "user_type": user_type},
    )
    return ok(_serialize_user(user), status=201)


@bp.patch("/organizations/me/users/<uuid:user_id>")
@require_auth
@require_scope("config:manage")
def update_org_user(user_id):
    org = _current_org()
    user = _get_org_user(user_id, org)
    payload = request.get_json(silent=True) or {}
    if "display_name" in payload:
        display_name = (payload.get("display_name") or "").strip()
        if not display_name or len(display_name) > 120:
            raise ValidationError("display_name is required (max 120 characters)")
        user.display_name = display_name
    if "is_active" in payload:
        if not isinstance(payload["is_active"], bool):
            raise ValidationError("is_active must be boolean")
        if user.id == g.user.id and payload["is_active"] is False:
            raise ConflictError("An administrator cannot deactivate the current user")
        user.is_active = payload["is_active"]
    if "password" in payload:
        password = payload.get("password")
        if not isinstance(password, str) or len(password) < 12:
            raise ValidationError("password must be at least 12 characters")
        user.password_hash = generate_password_hash(password)
    if not any(field in payload for field in ("display_name", "is_active", "password")):
        raise ValidationError("At least one supported user field is required")
    db.session.commit()
    record_audit(
        action="organization.user_updated",
        actor_id=str(g.user.id),
        target_type="user",
        target_id=user.id,
        organization_id=org.id,
        metadata={"changes": sorted(payload.keys())},
    )
    return ok(_serialize_user(user))


@bp.put("/organizations/me/users/<uuid:user_id>/roles")
@require_auth
@require_scope("config:manage")
def replace_org_user_roles(user_id):
    org = _current_org()
    user = _get_org_user(user_id, org)
    roles = _resolve_roles(org, (request.get_json(silent=True) or {}).get("roles"))
    if not roles:
        raise ValidationError("roles must contain at least one known role")
    if user.id == g.user.id and not any(role.name == "organization_administrator" for role in roles):
        raise ConflictError("An administrator cannot remove the current user's administrator role")
    user.roles = roles
    db.session.commit()
    record_audit(
        action="organization.user_roles_replaced",
        actor_id=str(g.user.id),
        target_type="user",
        target_id=user.id,
        organization_id=org.id,
        metadata={"roles": [role.name for role in roles]},
    )
    return ok(_serialize_user(user))


def _current_org() -> Organization:
    from flask import g

    org = getattr(g, "organization", None)
    if org is None:
        raise NotFoundError("Authenticated organization not found")
    return org


def _get_org_user(user_id, org):
    try:
        parsed = UUID(str(user_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError("user_id must be a valid UUID") from exc
    user = User.query.filter_by(id=parsed, organization_id=org.id).first()
    if user is None:
        raise NotFoundError("Organization user not found")
    return user


def _resolve_roles(org, names):
    if names is None:
        names = ["developer"]
    if not isinstance(names, list) or not names or any(not isinstance(name, str) for name in names):
        raise ValidationError("roles must be a non-empty list of role names")
    normalized = sorted({name.strip().lower() for name in names})
    if any(not is_known_role(name) for name in normalized):
        raise ValidationError("roles contains an unknown system role")
    ensure_roles(org)
    roles = Role.query.filter(Role.organization_id == org.id, Role.name.in_(normalized)).all()
    if len(roles) != len(normalized):
        raise ValidationError("One or more requested roles are unavailable")
    return roles


def _serialize_user(user):
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "roles": sorted(role.name for role in user.roles),
        "user_type": "automation" if user.external_provider == "automation" else "human",
        "is_active": user.is_active,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


def _effective_gate_policy(settings):
    policy = {**GATE_POLICY_DEFAULTS, **((settings or {}).get("gate_policy") or {})}
    policy.setdefault("version", "gate-policy-v1")
    return policy


def _validate_gate_policy(payload, partial=False):
    if not isinstance(payload, dict):
        raise ValidationError("gate policy must be an object")
    allowed = set(GATE_POLICY_DEFAULTS)
    unknown = sorted(set(payload) - allowed - {"version"})
    if unknown:
        raise ValidationError(f"Unsupported gate policy field(s): {', '.join(unknown)}")
    if not partial:
        missing = sorted(allowed - set(payload))
        if missing:
            raise ValidationError(f"Missing gate policy field(s): {', '.join(missing)}")
    updates = {}
    for key, value in payload.items():
        if key == "version":
            continue
        if key == "approval_mode":
            mode = str(value or "").strip().lower()
            if mode not in APPROVAL_MODES:
                raise ValidationError("approval_mode must be human_api, api_automation, or disabled")
            updates[key] = mode
        elif key in GATE_POLICY_DEFAULTS:
            if not isinstance(value, bool):
                raise ValidationError(f"{key} must be boolean")
            updates[key] = value
    return updates


def _next_policy_version(current):
    if not current or not str(current).startswith("gate-policy-v"):
        return "gate-policy-v2"
    try:
        number = int(str(current).rsplit("v", 1)[1])
    except ValueError:
        number = 1
    return f"gate-policy-v{number + 1}"
