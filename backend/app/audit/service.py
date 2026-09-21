import hashlib
import hmac
import json

from flask import current_app, g, request

from ..extensions import db
from ..models import AuditEvent
from ..utils import new_uuid, utcnow


def _hash_payload(plain: str, secret: str) -> str:
    return hmac.new(secret.encode(), plain.encode(), hashlib.sha256).hexdigest()


def _event_string(event: AuditEvent) -> str:
    parts = [
        str(event.id),
        str(event.organization_id or ""),
        event.actor_type,
        event.actor_id or "",
        event.action,
        event.target_type or "",
        event.target_id or "",
        event.correlation_id,
        event.result,
        str(event.created_at.isoformat()),
        json.dumps(event.data or {}, sort_keys=True, separators=(",", ":")),
    ]
    return "|".join(str(p) for p in parts)


def _audit_secret() -> str:
    if "audit_secret" not in g:
        g.audit_secret = current_app.config["AUDIT_SECRET"]
    return g.audit_secret


def record_audit(
    *,
    action: str,
    actor_type: str = "user",
    actor_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    result: str = "success",
    organization_id=None,
    metadata: dict | None = None,
    commit: bool = True,
    ip_address: str | None = None,
) -> AuditEvent:
    secret = _audit_secret()
    correlation_id = getattr(g, "correlation_id", None) or new_uuid().hex

    org_id = organization_id
    if org_id is None:
        org_id = getattr(g, "organization", None).id if getattr(g, "organization", None) else None
    if actor_id is None:
        user = getattr(g, "user", None)
        actor_id = str(user.id) if user else None
        if actor_id:
            actor_type = "user"
        elif actor_type == "user":
            actor_type = "system"
    actor_id = str(actor_id) if actor_id is not None else None

    prev_event = None
    if org_id:
        # Serialize writers per tenant so two concurrent events cannot fork the
        # hash chain. PostgreSQL row locking is used when an existing event is
        # available; the transaction still needs the advisory lock for the
        # first event and for SQLite/test databases.
        if db.engine.dialect.name == "postgresql":
            db.session.execute(
                db.text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": str(org_id)},
            )
        prev_event = (
            AuditEvent.query.filter_by(organization_id=org_id)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .first()
        )
    prev_hash = prev_event.event_hash if prev_event else None

    event = AuditEvent(
        id=new_uuid(),
        organization_id=org_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id else None,
        correlation_id=correlation_id,
        result=result,
        ip_address=ip_address,
        data=metadata or {},
        prev_hash=prev_hash,
        event_hash="",
        created_at=utcnow(),
    )
    try:
        event.ip_address = ip_address or request.remote_addr
    except RuntimeError:
        event.ip_address = ip_address
    event.event_hash = _hash_payload(f"{prev_hash or ''}|{_event_string(event)}", secret)
    db.session.add(event)
    if commit:
        db.session.commit()
    return event


def verify_chain(organization_id) -> dict:
    secret = _audit_secret()
    events = (
        AuditEvent.query.filter_by(organization_id=organization_id)
        .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        .all()
    )
    previous = None
    verified = 0
    for event in events:
        expected = _hash_payload(f"{previous or ''}|{_event_string(event)}", secret)
        if event.prev_hash != previous:
            return {
                "verified": False,
                "verified_count": verified,
                "total": len(events),
                "failure": f"link break before event {event.id}",
            }
        if event.event_hash != expected:
            return {
                "verified": False,
                "verified_count": verified,
                "total": len(events),
                "failure": f"hash mismatch at event {event.id}",
            }
        previous = event.event_hash
        verified += 1
    return {"verified": True, "verified_count": verified, "total": len(events), "failure": None}
