def create_project_payload(name="Acme", key="acme"):
    return {"name": name, "key": key, "description": "EXAMPLE repo", "default_branch": "main"}


def _create(client, headers, **overrides):
    payload = create_project_payload()
    payload.update(overrides)
    return client.post("/api/v1/projects", headers=headers, json=payload)


def test_create_and_get_project(client, auth_headers):
    resp = _create(client, auth_headers())
    assert resp.status_code == 201
    project = resp.get_json()["data"]
    assert project["key"] == "acme"
    assert project["lifecycle_state"] == "requirements"

    got = client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers())
    assert got.status_code == 200
    assert got.get_json()["data"]["name"] == "Acme"


def test_list_projects(client, auth_headers):
    _create(client, auth_headers(), key="alpha")
    _create(client, auth_headers(), key="beta", name="Beta")
    resp = client.get("/api/v1/projects", headers=auth_headers())
    assert resp.status_code == 200
    keys = [p["key"] for p in resp.get_json()["data"]]
    assert set(keys) == {"alpha", "beta"}


def test_duplicate_project_key_conflict(client, auth_headers):
    _create(client, auth_headers(), key="same")
    resp = _create(client, auth_headers(), key="same")
    assert resp.status_code == 409


def test_update_and_archive(client, auth_headers):
    project = _create(client, auth_headers()).get_json()["data"]
    resp = client.patch(
        f"/api/v1/projects/{project['id']}",
        headers=auth_headers(),
        json={"name": "Renamed", "lifecycle_state": "architecture"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["lifecycle_state"] == "architecture"

    arch = client.post(f"/api/v1/projects/{project['id']}/archive", headers=auth_headers())
    assert arch.status_code == 200
    assert arch.get_json()["data"]["archived"] is True
    listing = client.get("/api/v1/projects", headers=auth_headers()).get_json()["data"]
    assert all(p["archived"] is not True for p in listing)


def test_tenant_isolation(client, auth_headers, app, org):
    from app.auth.providers.local import LocalProvider
    from app.orgs.service import create_organization

    other = create_organization("Other Tenant", slug="tenant-x")
    LocalProvider(other.slug).ensure_local_user(
        "x-admin@other.local", "password123", "X Admin", ["organization_administrator"]
    )
    other_token = client.post(
        "/api/v1/auth/login",
        json={
            "email": "x-admin@other.local",
            "password": "password123",
            "organization": "tenant-x",
        },
    ).get_json()["data"]["token"]
    other_headers = {"Authorization": f"Bearer {other_token}"}

    project = _create(client, auth_headers()).get_json()["data"]
    got = client.get(f"/api/v1/projects/{project['id']}", headers=other_headers)
    assert got.status_code == 404
    listing = client.get("/api/v1/projects", headers=other_headers).get_json()["data"]
    assert listing == []


def test_project_audit_recorded(client, auth_headers, org):
    _create(client, auth_headers())
    from app.models import AuditEvent

    actions = [e.action for e in AuditEvent.query.filter_by(organization_id=org.id).all()]
    assert "project.created" in actions


def test_project_write_requires_project_write_scope(client, login, developer):
    developer_token = login(email="dev@test.local")
    headers = {"Authorization": f"Bearer {developer_token}"}
    response = _create(client, headers, key="developer-project")
    assert response.status_code in (401, 403)


def test_project_responsibility_assignments_are_project_scoped_and_audited(
    client, auth_headers, org, admin, developer
):
    from app.models import AuditEvent

    project = _create(client, auth_headers(), key="responsibilities").get_json()["data"]
    create = client.post(
        f"/api/v1/projects/{project['id']}/responsibility-assignments",
        headers=auth_headers(),
        json={
            "user_id": str(developer.id),
            "responsibility_type": "developer",
            "effective_from": "2026-01-01T00:00:00Z",
        },
    )
    assert create.status_code == 201
    assignment = create.get_json()["data"]
    assert assignment["user_id"] == str(developer.id)
    assert assignment["segregation_group"] == "implementation_quality"

    listed = client.get(
        f"/api/v1/projects/{project['id']}/responsibility-assignments?as_of=2026-02-01T00:00:00Z",
        headers=auth_headers(),
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.get_json()["data"]] == [assignment["id"]]

    conflict = client.post(
        f"/api/v1/projects/{project['id']}/responsibility-assignments",
        headers=auth_headers(),
        json={
            "user_id": str(developer.id),
            "responsibility_type": "qa_reviewer",
            "effective_from": "2026-01-01T00:00:00Z",
        },
    )
    assert conflict.status_code == 409

    changed = client.patch(
        f"/api/v1/projects/{project['id']}/responsibility-assignments/{assignment['id']}",
        headers=auth_headers(),
        json={"effective_until": "2026-12-31T00:00:00Z", "is_primary": False},
    )
    assert changed.status_code == 200
    assert changed.get_json()["data"]["is_primary"] is False
    actions = [
        event.action
        for event in AuditEvent.query.filter_by(organization_id=org.id).all()
    ]
    assert "project.responsibility_assigned" in actions
    assert "project.responsibility_updated" in actions


def test_project_responsibility_assignment_requires_config_scope(client, login, developer, auth_headers):
    project = _create(client, auth_headers(), key="scope-check").get_json()["data"]
    developer_headers = {"Authorization": f"Bearer {login(email='dev@test.local')}"}
    response = client.post(
        f"/api/v1/projects/{project['id']}/responsibility-assignments",
        headers=developer_headers,
        json={
            "user_id": str(developer.id),
            "responsibility_type": "developer",
            "effective_from": "2026-01-01T00:00:00Z",
        },
    )
    assert response.status_code in (401, 403)
