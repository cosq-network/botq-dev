import json

import pytest
from sqlalchemy import text

from app.audit.service import record_audit, verify_chain
from app.extensions import db
from app.models import AuditEvent


def _record(org, action, result="success", metadata=None):
    return record_audit(
        action=action,
        actor_type="user",
        actor_id="someone",
        target_type="project",
        target_id="t1",
        organization_id=org.id,
        metadata=metadata,
    )


def test_chain_verifies(org):
    _record(org, "project.created", metadata={"n": 1})
    _record(org, "project.updated", metadata={"n": 2})
    report = verify_chain(org.id)
    assert report["verified"] is True
    assert report["total"] == 2
    events = (
        AuditEvent.query.filter_by(organization_id=org.id)
        .order_by(AuditEvent.created_at.asc())
        .all()
    )
    assert events[1].prev_hash == events[0].event_hash
    assert events[0].prev_hash is None


def test_chains_are_independent(org):
    from app.orgs.service import create_organization

    _record(org, "a.created")
    other = create_organization("Other", slug="other2")
    _record(other, "b.created")
    assert verify_chain(org.id)["total"] == 1
    assert verify_chain(other.id)["total"] == 1


def test_tamper_detected(org):
    _record(org, "a.created", metadata={"amount": 100})
    _record(org, "b.created")
    target = AuditEvent.query.filter_by(action="a.created").one()
    db.session.execute(
        text("UPDATE audit_events SET data = :d WHERE id = :id"),
        {"d": json.dumps({"amount": 99999}), "id": target.id.hex},
    )
    db.session.commit()
    db.session.expire_all()
    report = verify_chain(org.id)
    assert report["verified"] is False
    assert report["failure"]


def test_orm_update_blocked(org):
    event = record_audit(action="a.created", actor_id="x", organization_id=org.id)
    event.data = {"changed": True}
    with pytest.raises(PermissionError):
        db.session.commit()


def test_orm_delete_blocked(org):
    event = record_audit(action="a.created", actor_id="x", organization_id=org.id)
    db.session.delete(event)
    with pytest.raises(PermissionError):
        db.session.commit()


def test_audit_list_requires_scope(client, auth_headers):
    resp = client.get("/api/v1/audit/events", headers=auth_headers())
    assert resp.status_code == 200
    assert "events" in resp.get_json()["data"]


def test_audit_verify_endpoint(client, auth_headers):
    resp = client.get("/api/v1/audit/verify", headers=auth_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"]["verified"] is True


def test_correlation_ids_differ(client, auth_headers):
    r1 = client.get("/api/v1/projects", headers=auth_headers())
    r2 = client.get("/api/v1/projects", headers=auth_headers())
    assert r1.get_json()["correlation_id"]
    assert r1.get_json()["correlation_id"] != r2.get_json()["correlation_id"]
