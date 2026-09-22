import pytest

from app.extensions import db
from app.models import Approval


def _content():
    return {
        "goals": ["Ship safely"],
        "functional_specifications": ["Approve baselines"],
        "constraints": [],
        "acceptance_expectations": ["Gate blocks unapproved"],
        "attachments": [],
        "repository_references": [],
    }


def _login(client, email, org_slug, password="password123"):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "organization": org_slug},
    ).get_json()["data"]["token"]


def _make_reviewer(org):
    from app.auth.providers.local import LocalProvider

    user = LocalProvider(org.slug).ensure_local_user(
        "owner@test.local", "password123", "Product Owner", ["product_owner"]
    )
    return user


def _make_author_other(org):
    from app.auth.providers.local import LocalProvider

    return LocalProvider(org.slug).ensure_local_user(
        "author2@test.local", "password123", "Other Author", ["product_owner"]
    )


def _baseline(client, headers, project_id, submit=True, title="Baseline"):
    created = client.post(
        "/api/v1/requirements/baselines",
        headers=headers,
        json={"project_id": project_id, "title": title, "content": _content()},
    ).get_json()["data"]
    if submit:
        client.post(f"/api/v1/requirements/baselines/{created['id']}/submit", headers=headers)
    return created


def _project(client, headers, key):
    return client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": key.title(), "key": key, "default_branch": "main"},
    ).get_json()["data"]


def test_approve_flow_binds_to_version_and_hash(client, auth_headers, app, org):
    admin = auth_headers()
    project = _project(client, admin, "appr1")
    baseline = _baseline(client, admin, project["id"], title="EXAMPLE Baseline")
    reviewer = _make_reviewer(org)
    reviewer_headers = {"Authorization": f"Bearer {_login(client, 'owner@test.local', org.slug)}"}

    approved = client.post(
        f"/api/v1/requirements/baselines/{baseline['id']}/approve", headers=reviewer_headers
    )
    assert approved.status_code == 200
    assert approved.get_json()["data"]["status"] == "approved"

    history = client.get(
        f"/api/v1/approvals?artifact_type=requirement_baseline&artifact_id={baseline['id']}",
        headers=reviewer_headers,
    ).get_json()["data"]
    assert len(history) == 1
    assert history[0]["decision"] == "approved"
    assert history[0]["artifact_version"] == 1
    assert history[0]["artifact_hash"] == baseline["content_hash"]
    assert history[0]["self_approval"] is False
    assert reviewer  # created reviewer used above


def test_self_approval_is_rejected_by_segregation_of_duties(client, auth_headers):
    headers = auth_headers()
    project = _project(client, headers, "appr2")
    baseline = _baseline(client, headers, project["id"], title="Self")
    resp = client.post(f"/api/v1/requirements/baselines/{baseline['id']}/approve", headers=headers)
    assert resp.status_code == 409
    assert resp.get_json()["error"]["code"] == "segregation_of_duties"


def test_approve_requires_submission(client, auth_headers, org):
    admin = auth_headers()
    project = _project(client, admin, "appr3")
    draft = _baseline(client, admin, project["id"], submit=False, title="DraftOnly")
    _make_reviewer(org)
    reviewer_headers = {"Authorization": f"Bearer {_login(client, 'owner@test.local', org.slug)}"}
    resp = client.post(
        f"/api/v1/requirements/baselines/{draft['id']}/approve", headers=reviewer_headers
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"]["code"] == "invalid_baseline_state"


def test_approve_requires_approval_scope(client, auth_headers, app, org):
    admin = auth_headers()
    project = _project(client, admin, "appr4")
    baseline = _baseline(client, admin, project["id"], title="Scoped")
    from app.auth.providers.local import LocalProvider

    LocalProvider(org.slug).ensure_local_user(
        "dev4@test.local", "password123", "Dev", ["developer"]
    )
    dev_headers = {"Authorization": f"Bearer {_login(client, 'dev4@test.local', org.slug)}"}
    resp = client.post(
        f"/api/v1/requirements/baselines/{baseline['id']}/approve", headers=dev_headers
    )
    assert resp.status_code == 401


def test_new_version_requires_fresh_approval(client, auth_headers, org):
    admin = auth_headers()
    project = _project(client, admin, "appr5")
    baseline = _baseline(client, admin, project["id"], title="Versioned")
    _make_reviewer(org)
    reviewer_headers = {"Authorization": f"Bearer {_login(client, 'owner@test.local', org.slug)}"}

    assert (
        client.post(
            f"/api/v1/requirements/baselines/{baseline['id']}/approve", headers=reviewer_headers
        ).get_json()["data"]["status"]
        == "approved"
    )

    # Author revises -> new version, back to draft; approval no longer applies
    revised = client.post(
        f"/api/v1/requirements/baselines/{baseline['id']}/versions",
        headers=admin,
        json={"content": {**_content(), "constraints": ["extra"]}},
    ).get_json()["data"]
    assert revised["status"] == "draft"
    assert revised["current_version"] == 2

    too_early = client.post(
        f"/api/v1/requirements/baselines/{baseline['id']}/approve", headers=reviewer_headers
    )
    assert too_early.status_code == 409

    client.post(f"/api/v1/requirements/baselines/{baseline['id']}/submit", headers=admin)
    state = client.get(
        f"/api/v1/approvals/artifact/requirement_baseline/{baseline['id']}", headers=admin
    ).get_json()["data"]
    assert state["version"] == 2
    assert all(a["artifact_version"] == 1 for a in state["approvals"])
    assert (
        client.post(
            f"/api/v1/requirements/baselines/{baseline['id']}/approve", headers=reviewer_headers
        ).get_json()["data"]["status"]
        == "approved"
    )


def test_stale_hash_binding_rejected(client, auth_headers, org):
    admin = auth_headers()
    project = _project(client, admin, "appr6")
    baseline = _baseline(client, admin, project["id"], title="Stale")
    _make_reviewer(org)
    reviewer_headers = {"Authorization": f"Bearer {_login(client, 'owner@test.local', org.slug)}"}
    resp = client.post(
        f"/api/v1/requirements/baselines/{baseline['id']}/approve",
        headers=reviewer_headers,
        json={"version": baseline["current_version"], "content_hash": "0" * 64},
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"]["code"] == "stale_artifact_hash"


def test_waive_requires_reason_and_expiry(client, auth_headers, org):
    admin = auth_headers()
    project = _project(client, admin, "appr7")
    baseline = _baseline(client, admin, project["id"], title="Waive")
    _make_reviewer(org)
    reviewer_headers = {"Authorization": f"Bearer {_login(client, 'owner@test.local', org.slug)}"}

    no_reason = client.post(
        f"/api/v1/requirements/baselines/{baseline['id']}/waive", headers=reviewer_headers
    )
    assert no_reason.status_code == 422

    no_expiry = client.post(
        f"/api/v1/requirements/baselines/{baseline['id']}/waive",
        headers=reviewer_headers,
        json={"reason": "EXAMPLE exception"},
    )
    assert no_expiry.status_code == 422

    waived = client.post(
        f"/api/v1/requirements/baselines/{baseline['id']}/waive",
        headers=reviewer_headers,
        json={"reason": "EXAMPLE exception", "expires_at": "2030-01-01T00:00:00"},
    )
    assert waived.status_code == 200
    assert waived.get_json()["data"]["status"] == "waived"


def test_cancel_by_author(client, auth_headers):
    admin = auth_headers()
    project = _project(client, admin, "appr8")
    baseline = _baseline(client, admin, project["id"], title="Cancel")
    cancelled = client.post(
        f"/api/v1/requirements/baselines/{baseline['id']}/cancel", headers=admin
    )
    assert cancelled.status_code == 200
    assert cancelled.get_json()["data"]["status"] == "cancelled"


def test_approvals_are_immutable(client, auth_headers, org, app):
    admin = auth_headers()
    project = _project(client, admin, "appr9")
    baseline = _baseline(client, admin, project["id"], title="Immutable")
    _make_reviewer(org)
    reviewer_headers = {"Authorization": f"Bearer {_login(client, 'owner@test.local', org.slug)}"}
    client.post(
        f"/api/v1/requirements/baselines/{baseline['id']}/approve", headers=reviewer_headers
    )

    approval = Approval.query.filter_by(artifact_id=baseline["id"]).one()
    approval.decision = "rejected"
    with pytest.raises(PermissionError):
        db.session.commit()
    db.session.rollback()


def test_generic_approval_endpoint(client, auth_headers, org):
    admin = auth_headers()
    project = _project(client, admin, "apprg")
    baseline = _baseline(client, admin, project["id"], title="Generic")
    _make_reviewer(org)
    reviewer_headers = {"Authorization": f"Bearer {_login(client, 'owner@test.local', org.slug)}"}
    resp = client.post(
        "/api/v1/approvals",
        headers=reviewer_headers,
        json={
            "artifact_type": "requirement_baseline",
            "artifact_id": baseline["id"],
            "decision": "rejected",
            "reason": "not aligned",
        },
    )
    assert resp.status_code == 201
    assert resp.get_json()["data"]["decision"] == "rejected"
    got = client.get(f"/api/v1/requirements/baselines/{baseline['id']}", headers=admin)
    assert got.get_json()["data"]["status"] == "rejected"


def test_unsupported_artifact_type(client, auth_headers, org):
    _make_reviewer(org)
    reviewer_headers = {"Authorization": f"Bearer {_login(client, 'owner@test.local', org.slug)}"}
    resp = client.post(
        "/api/v1/approvals",
        headers=reviewer_headers,
        json={
            "artifact_type": "mystery",
            "artifact_id": "00000000-0000-0000-0000-000000000000",
            "decision": "approved",
        },
    )
    assert resp.status_code == 422
