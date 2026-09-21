import uuid

import pytest

from app.extensions import db
from app.models import AuditEvent, RequirementBaseline, RequirementBaselineVersion
from app.requirements.service import content_hash, diff_contents, normalize_content


def _content(**overrides):
    content = {
        "goals": ["Let operators deliver software safely"],
        "functional_specifications": ["Create projects", "Track requirements"],
        "constraints": ["Runs on a single VPS"],
        "acceptance_expectations": ["Baseline approval gate works"],
        "attachments": [{"name": "intake.pdf", "url": "https://example.com/intake.pdf"}],
        "repository_references": [{"url": "git@github.com:acme/pilot.git", "ref": "main"}],
    }
    content.update(overrides)
    return content


def _create_project(client, headers, key="pilot"):
    return client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": key.title(), "key": key, "default_branch": "main"},
    ).get_json()["data"]


def _create_baseline(client, headers, project_id, **overrides):
    payload = {"project_id": project_id, "title": "Pilot Intake", "content": _content()}
    payload.update(overrides)
    return client.post("/api/v1/requirements/baselines", headers=headers, json=payload)


def test_normalize_content_requires_goals():
    from app.errors import ValidationError

    with pytest.raises(ValidationError):
        normalize_content({"goals": []})
    with pytest.raises(ValidationError):
        normalize_content({"goals": ["ok"], "attachments": [{"sha256": "x"}]})


def test_content_hash_is_stable():
    assert content_hash(normalize_content(_content())) == content_hash(
        normalize_content(_content())
    )
    assert content_hash(normalize_content(_content())) != content_hash(
        normalize_content(_content(goals=["different"]))
    )


def test_diff_contents_detects_add_remove_change():
    old = normalize_content(_content())
    new = normalize_content(
        _content(
            goals=["Let operators deliver software safely", "Reduce toil"],
            constraints=[],
        )
    )
    diff = diff_contents(old, new)
    assert diff["material"] is True
    assert diff["added"]["goals"] == ["Reduce toil"]
    assert diff["removed"]["constraints"] == ["Runs on a single VPS"]


def test_create_get_and_version_baseline(client, auth_headers):
    headers = auth_headers()
    project = _create_project(client, headers)
    resp = _create_baseline(client, headers, project["id"])
    assert resp.status_code == 201
    baseline = resp.get_json()["data"]
    assert baseline["status"] == "draft"
    assert baseline["current_version"] == 1
    assert baseline["content"]["goals"] == ["Let operators deliver software safely"]

    revised = client.post(
        f"/api/v1/requirements/baselines/{baseline['id']}/versions",
        headers=headers,
        json={"content": _content(goals=["Deliver software safely", "Reduce toil"])},
    )
    assert revised.status_code == 201
    updated = revised.get_json()["data"]
    assert updated["current_version"] == 2
    assert updated["version_count"] == 2

    first = client.get(
        f"/api/v1/requirements/baselines/{baseline['id']}/versions/1", headers=headers
    )
    assert first.status_code == 200
    assert first.get_json()["data"]["content"]["goals"] == ["Let operators deliver software safely"]

    comparison = client.get(
        f"/api/v1/requirements/baselines/{baseline['id']}/versions/1/diff?to=2", headers=headers
    )
    assert comparison.status_code == 200
    assert comparison.get_json()["data"]["diff"]["material"] is True


def test_versions_are_immutable_at_orm_level(client, auth_headers, app):
    headers = auth_headers()
    project = _create_project(client, headers, key="immutable")
    baseline = _create_baseline(client, headers, project["id"]).get_json()["data"]
    version = RequirementBaselineVersion.query.filter_by(
        baseline_id=uuid.UUID(baseline["id"])
    ).one()

    version.change_summary = "tampering"
    with pytest.raises(PermissionError):
        db.session.commit()
    db.session.rollback()


def test_identical_revision_is_rejected(client, auth_headers):
    headers = auth_headers()
    project = _create_project(client, headers, key="samehash")
    baseline = _create_baseline(client, headers, project["id"]).get_json()["data"]
    resp = client.post(
        f"/api/v1/requirements/baselines/{baseline['id']}/versions",
        headers=headers,
        json={"content": _content()},
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"]["code"] == "no_change"


def test_submit_and_resubmit_flow(client, auth_headers):
    headers = auth_headers()
    project = _create_project(client, headers, key="submit")
    baseline = _create_baseline(client, headers, project["id"]).get_json()["data"]

    submitted = client.post(
        f"/api/v1/requirements/baselines/{baseline['id']}/submit", headers=headers
    )
    assert submitted.status_code == 200
    assert submitted.get_json()["data"]["status"] == "submitted"

    again = client.post(f"/api/v1/requirements/baselines/{baseline['id']}/submit", headers=headers)
    assert again.status_code == 409

    revised = client.post(
        f"/api/v1/requirements/baselines/{baseline['id']}/versions",
        headers=headers,
        json={"content": _content(constraints=["New constraint"])},
    )
    assert revised.status_code == 201
    assert revised.get_json()["data"]["status"] == "draft"


def test_duplicate_title_conflict(client, auth_headers):
    headers = auth_headers()
    project = _create_project(client, headers, key="dupe")
    _create_baseline(client, headers, project["id"])
    resp = _create_baseline(client, headers, project["id"])
    assert resp.status_code == 409
    assert resp.get_json()["error"]["code"] == "duplicate_baseline_title"


def test_invalid_project_reference(client, auth_headers):
    headers = auth_headers()
    resp = _create_baseline(client, headers, "not-a-uuid")
    assert resp.status_code == 422
    missing = _create_baseline(client, headers, "00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404


def test_tenant_isolation(client, auth_headers, app):
    from app.auth.providers.local import LocalProvider
    from app.orgs.service import create_organization

    headers = auth_headers()
    project = _create_project(client, headers, key="iso")
    baseline = _create_baseline(client, headers, project["id"]).get_json()["data"]

    other = create_organization("Other Requirement Tenant", slug="req-tenant")
    LocalProvider(other.slug).ensure_local_user(
        "other@req.local", "password123", "Other", ["organization_administrator"]
    )
    other_token = client.post(
        "/api/v1/auth/login",
        json={
            "email": "other@req.local",
            "password": "password123",
            "organization": other.slug,
        },
    ).get_json()["data"]["token"]
    other_headers = {"Authorization": f"Bearer {other_token}"}

    got = client.get(f"/api/v1/requirements/baselines/{baseline['id']}", headers=other_headers)
    assert got.status_code == 404
    listing = client.get("/api/v1/requirements/baselines", headers=other_headers).get_json()["data"]
    assert listing == []


def test_requirements_require_scope(client, auth_headers, app, org):
    from app.auth.providers.local import LocalProvider

    headers = auth_headers()
    project = _create_project(client, headers, key="scoped")

    LocalProvider(org.slug).ensure_local_user(
        "architect@test.local", "password123", "Architect", ["architect"]
    )
    token = client.post(
        "/api/v1/auth/login",
        json={
            "email": "architect@test.local",
            "password": "password123",
            "organization": org.slug,
        },
    ).get_json()["data"]["token"]
    architect_headers = {"Authorization": f"Bearer {token}"}

    read_ok = client.get("/api/v1/requirements/baselines", headers=architect_headers)
    assert read_ok.status_code == 200
    write_denied = client.post(
        "/api/v1/requirements/baselines",
        headers=architect_headers,
        json={"project_id": project["id"], "title": "Nope", "content": _content()},
    )
    assert write_denied.status_code == 401


def test_baseline_audit_recorded(client, auth_headers, org):
    headers = auth_headers()
    project = _create_project(client, headers, key="audited")
    baseline = _create_baseline(client, headers, project["id"]).get_json()["data"]
    client.post(
        f"/api/v1/requirements/baselines/{baseline['id']}/versions",
        headers=headers,
        json={"content": _content(constraints=[])},
    )
    client.post(f"/api/v1/requirements/baselines/{baseline['id']}/submit", headers=headers)

    actions = [e.action for e in AuditEvent.query.filter_by(organization_id=org.id).all()]
    assert "requirement_baseline.created" in actions
    assert "requirement_baseline.version_created" in actions
    assert "requirement_baseline.submitted" in actions
    assert RequirementBaseline.query.filter_by(organization_id=org.id).count() == 1
