from app.models import Organization


def test_bootstrap_org_needs_token(client):
    resp = client.post("/api/v1/organizations", json={"name": "Acme"})
    assert resp.status_code == 403


def test_bootstrap_org(client, app):
    resp = client.post(
        "/api/v1/organizations",
        headers={"X-Bootstrap-Token": "test-secret-key"},
        json={"name": "Acme Corp", "slug": "acme"},
    )
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["slug"] == "acme"
    org = Organization.query.filter_by(slug="acme").first()
    assert org is not None
    assert {r.name for r in org.roles} >= {
        "organization_administrator",
        "product_owner",
        "developer",
        "auditor",
        "security_approver",
    }


def test_duplicate_slug_rejected(client):
    headers = {"X-Bootstrap-Token": "test-secret-key"}
    assert (
        client.post(
            "/api/v1/organizations", headers=headers, json={"name": "A", "slug": "acme"}
        ).status_code
        == 201
    )
    resp = client.post("/api/v1/organizations", headers=headers, json={"name": "B", "slug": "acme"})
    assert resp.status_code == 409


def test_org_me_and_roles(client, auth_headers):
    resp = client.get("/api/v1/organizations/me", headers=auth_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"]["slug"] == "test"

    roles = client.get("/api/v1/organizations/me/roles", headers=auth_headers())
    payload = roles.get_json()["data"]
    names = {r["name"] for r in payload}
    assert "organization_administrator" in names
    admin = next(r for r in payload if r["name"] == "organization_administrator")
    assert "admin" in admin["scopes"]


def test_list_orgs_requires_bootstrap_token(client, auth_headers):
    resp = client.get("/api/v1/organizations", headers=auth_headers())
    assert resp.status_code == 403


def test_audit_event_on_org_bootstrap(client, app):
    client.post(
        "/api/v1/organizations",
        headers={"X-Bootstrap-Token": "test-secret-key"},
        json={"name": "Trace Co", "slug": "trace"},
    )
    from app.models import AuditEvent

    event = AuditEvent.query.filter_by(action="organization.created").first()
    assert event is not None
    assert len(event.event_hash) == 64
    assert event.actor_type == "system"


def test_admin_can_create_user_assign_roles_and_update_settings(client, auth_headers, org):
    created = client.post(
        "/api/v1/organizations/me/users",
        headers=auth_headers(),
        json={
            "email": "qa@example.test",
            "display_name": "QA Reviewer",
            "password": "correct-horse-battery-12",
            "roles": ["qa_engineer"],
        },
    )
    assert created.status_code == 201
    user = created.get_json()["data"]
    assert user["roles"] == ["qa_engineer"]

    updated_roles = client.put(
        f"/api/v1/organizations/me/users/{user['id']}/roles",
        headers=auth_headers(),
        json={"roles": ["qa_engineer", "auditor"]},
    )
    assert updated_roles.status_code == 200
    assert set(updated_roles.get_json()["data"]["roles"]) == {"auditor", "qa_engineer"}

    settings = client.patch(
        "/api/v1/organizations/me/settings",
        headers=auth_headers(),
        json={"enforce_project_responsibilities": True},
    )
    assert settings.status_code == 200
    assert settings.get_json()["data"]["settings"]["enforce_project_responsibilities"] is True


def test_admin_can_configure_organization_gate_policy(client, auth_headers):
    current = client.get("/api/v1/organizations/me/gate-policy", headers=auth_headers())
    assert current.status_code == 200
    assert current.get_json()["data"]["approval_mode"] == "human_api"

    updated = client.patch(
        "/api/v1/organizations/me/gate-policy",
        headers=auth_headers(),
        json={"approval_mode": "api_automation", "require_previous_gate_closed": False},
    )
    assert updated.status_code == 200
    data = updated.get_json()["data"]
    assert data["approval_mode"] == "api_automation"
    assert data["require_previous_gate_closed"] is False
    assert data["version"] == "gate-policy-v2"
