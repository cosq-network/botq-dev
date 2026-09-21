from flask import Blueprint, current_app, g, request

from ..api.responses import ok
from ..audit.service import record_audit
from ..errors import AuthenticationError, NotFoundError, ValidationError
from ..extensions import db
from ..models import Secret
from ..utils import new_uuid, utcnow
from .manager import decrypt_value, encrypt_value, key_hint, random_secret_value
from .masking import mask_value

bp = Blueprint("secrets", __name__, url_prefix="/secrets")


def _serialize(secret: Secret) -> dict:
    return {
        "id": str(secret.id),
        "name": secret.name,
        "purpose": secret.purpose,
        "secret_store": secret.secret_store,
        "status": secret.status,
        "key_ref": secret.key_ref,
        "last_accessed_at": secret.last_accessed_at.isoformat()
        if secret.last_accessed_at
        else None,
        "last_rotated_at": secret.last_rotated_at.isoformat() if secret.last_rotated_at else None,
        "created_at": secret.created_at.isoformat(),
        "updated_at": secret.updated_at.isoformat(),
    }


@bp.post("")
def create_secret():
    _require_secret_scope()
    org = _org()
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    value = payload.get("value")
    purpose = (payload.get("purpose") or "").strip() or None
    if not name or value is None:
        raise ValidationError("name and value are required")
    if Secret.query.filter_by(organization_id=org.id, name=name).first():
        from ..errors import ConflictError

        raise ConflictError("Secret name already exists", code="duplicate_secret_name")
    encrypted = encrypt_value(
        value,
        current_app.config["SECRET_KEY"],
        current_app.config["SECRET_ENCRYPTION_KEY"],
    )
    secret = Secret(
        id=new_uuid(),
        organization_id=org.id,
        name=name,
        purpose=purpose,
        encrypted_value=encrypted,
        secret_store="local",  # nosec B106 - storage backend enum value.
        status="active",
    )
    db.session.add(secret)
    db.session.commit()
    record_audit(
        action="secret.created",
        actor_id=str(g.user.id),
        target_type="secret",
        target_id=secret.id,
        organization_id=org.id,
        metadata={"name": name, "purpose": purpose, "key_hint": key_hint(value)},
    )
    return ok(_serialize(secret), status=201)


@bp.get("")
def list_secrets():
    _require_secret_scope()
    secrets = Secret.query.filter_by(organization_id=_org().id).all()
    return ok([_serialize(s) for s in secrets])


@bp.get("/<uuid:secret_id>")
def get_secret(secret_id):
    _require_secret_scope()
    secret = _get_owned(secret_id)
    secret.last_accessed_at = utcnow()
    db.session.commit()
    record_audit(
        action="secret.accessed",
        actor_id=str(g.user.id),
        target_type="secret",
        target_id=secret.id,
        organization_id=_org().id,
        metadata={"name": secret.name},
    )
    return ok(_serialize(secret))


@bp.post("/<uuid:secret_id>/rotate")
def rotate_secret(secret_id):
    _require_secret_scope()
    secret = _get_owned(secret_id)
    payload = request.get_json(silent=True) or {}
    new_value = payload.get("value")
    if new_value is None:
        if secret.secret_store != "local":  # nosec B105 - storage backend enum value.
            raise ValidationError("value is required for rotation when using an external store")
        new_value = random_secret_value()
    secret.encrypted_value = encrypt_value(
        new_value,
        current_app.config["SECRET_KEY"],
        current_app.config["SECRET_ENCRYPTION_KEY"],
    )
    secret.last_rotated_at = utcnow()
    secret.status = "active"
    db.session.commit()
    record_audit(
        action="secret.rotated",
        actor_id=str(g.user.id),
        target_type="secret",
        target_id=secret.id,
        organization_id=_org().id,
        metadata={"name": secret.name},
    )
    return ok(_serialize(secret))


@bp.post("/<uuid:secret_id>/revoke")
def revoke_secret(secret_id):
    _require_secret_scope()
    secret = _get_owned(secret_id)
    secret.status = "revoked"
    db.session.commit()
    record_audit(
        action="secret.revoked",
        actor_id=str(g.user.id),
        target_type="secret",
        target_id=secret.id,
        organization_id=_org().id,
        metadata={"name": secret.name},
    )
    return ok(_serialize(secret))


@bp.post("/<uuid:secret_id>/verify")
def verify_secret(secret_id):
    _require_secret_scope()
    secret = _get_owned(secret_id)
    try:
        plaintext = (
            decrypt_value(
                secret.encrypted_value,
                current_app.config["SECRET_KEY"],
                current_app.config["SECRET_ENCRYPTION_KEY"],
            )
            if secret.encrypted_value
            else None
        )
        verified = bool(plaintext)
    except Exception:
        verified = False
    record_audit(
        action="secret.verified",
        actor_id=str(g.user.id),
        target_type="secret",
        target_id=secret.id,
        organization_id=_org().id,
        metadata={"name": secret.name, "verified": verified},
    )
    return ok(
        {
            "id": str(secret.id),
            "name": secret.name,
            "verified": verified,
            "masked": mask_value(secret.encrypted_value),
        }
    )


def _require_secret_scope() -> None:
    from ..auth.roles import has_scope

    user = getattr(g, "user", None)
    if user is None or not has_scope(user, "secret:manage"):
        raise AuthenticationError("secret:manage scope required")


def _org():
    org = getattr(g, "organization", None)
    if org is None:
        raise AuthenticationError("Authenticated organization not found")
    return org


def _get_owned(secret_id) -> Secret:
    secret = Secret.query.filter_by(id=secret_id, organization_id=_org().id).first()
    if secret is None:
        raise NotFoundError("Secret not found")
    return secret
