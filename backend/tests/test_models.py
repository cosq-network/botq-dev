import uuid
from datetime import UTC, datetime

import pytest

from app.extensions import db
from app.models import Project, Role, User
from app.orgs.service import create_organization


def test_entity_ids_are_uuid(org, admin):
    assert isinstance(org.id, uuid.UUID)
    assert isinstance(admin.id, uuid.UUID)
    role = Role.query.filter_by(organization_id=org.id, name="developer").first()
    assert isinstance(role.id, uuid.UUID)


def test_org_scoped_roles_created(org):
    names = {r.name for r in Role.query.filter_by(organization_id=org.id).all()}
    assert names >= {
        "organization_administrator",
        "product_owner",
        "architect",
        "developer",
        "designer",
        "qa_engineer",
        "security_approver",
        "release_manager",
        "auditor",
        "ai_agent",
    }
    developer = Role.query.filter_by(organization_id=org.id, name="developer").first()
    assert "sandbox:run" in developer.scopes
    assert "secret:manage" not in developer.scopes


def test_timestamps_are_naive_utc(org):
    assert org.created_at.tzinfo is None
    org2 = create_organization("Ts Co", slug="tsco")
    now = datetime.now(UTC).replace(tzinfo=None)
    assert (now - org2.created_at).total_seconds() < 5


def test_user_requires_org(org):
    from sqlalchemy.exc import IntegrityError

    u = User(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        email="orphan@example.com",
        display_name="Orphan",
    )
    db.session.add(u)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_roles_unique_per_org(org):
    other = create_organization("Z", slug="zorg")
    r1 = Role.query.filter_by(organization_id=org.id, name="developer").first()
    r2 = Role.query.filter_by(organization_id=other.id, name="developer").first()
    assert r1.id != r2.id
    assert r1.organization_id != r2.organization_id


def test_project_tenant_columns(org):
    other = create_organization("T2", slug="t2")
    p1 = Project(name="P1", key="p1", organization_id=org.id)
    p2 = Project(name="P2", key="p2", organization_id=other.id)
    db.session.add_all([p1, p2])
    db.session.commit()
    assert Project.query.filter_by(organization_id=org.id).count() == 1
    assert Project.query.filter_by(organization_id=other.id).count() == 1
