from flask import Blueprint, g, request

from ..api.responses import ok
from ..auth.roles import has_scope
from ..errors import AuthenticationError, AuthorizationError
from ..models import AuditEvent
from .service import verify_chain

bp = Blueprint("audit", __name__, url_prefix="/audit")


def _require_audit_scope() -> None:
    user = getattr(g, "user", None)
    if user is None:
        raise AuthenticationError()
    if not has_scope(user, "audit:read"):
        raise AuthorizationError("audit:read scope required")


@bp.get("/events")
def list_events():
    _require_audit_scope()
    org = _org()
    limit = min(request.args.get("limit", default=50, type=int), 500)
    offset = request.args.get("offset", default=0, type=int)
    query = AuditEvent.query.filter_by(organization_id=org.id).order_by(
        AuditEvent.created_at.desc()
    )
    total = query.count()
    events = query.offset(offset).limit(limit).all()
    return ok(
        {
            "total": total,
            "limit": limit,
            "offset": offset,
            "events": [_serialize(e) for e in events],
        }
    )


@bp.get("/verify")
def verify():
    _require_audit_scope()
    report = verify_chain(_org().id)
    return ok(report)


@bp.get("/export")
def export():
    _require_audit_scope()
    events = (
        AuditEvent.query.filter_by(organization_id=_org().id)
        .order_by(AuditEvent.created_at.asc())
        .all()
    )
    return ok({"count": len(events), "events": [_serialize(e) for e in events]})


def _serialize(event: AuditEvent) -> dict:
    return {
        "id": str(event.id),
        "actor_type": event.actor_type,
        "actor_id": event.actor_id,
        "action": event.action,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "correlation_id": event.correlation_id,
        "result": event.result,
        "ip_address": event.ip_address,
        "metadata": event.data or {},
        "prev_hash": event.prev_hash,
        "event_hash": event.event_hash,
        "created_at": event.created_at.isoformat(),
    }


def _org():
    org = getattr(g, "organization", None)
    if org is None:
        raise AuthenticationError("Authenticated organization not found")
    return org
