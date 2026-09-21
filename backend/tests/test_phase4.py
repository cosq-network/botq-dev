from datetime import datetime, timedelta

from app.auth.providers.local import LocalProvider


def _login(client, email, org_slug):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123", "organization": org_slug},
    )
    return {"Authorization": "Bearer " + response.get_json()["data"]["token"]}


def _setup_approved_architecture(client, admin, reviewer, project_id):
    content = {
        "goals": ["Deliver a reviewable interface"],
        "functional_specifications": ["Users can view a dashboard"],
        "constraints": [],
        "acceptance_expectations": ["Dashboard returns status 200"],
        "attachments": [],
        "repository_references": [],
    }
    baseline = client.post(
        "/api/v1/requirements/baselines",
        headers=admin,
        json={"project_id": project_id, "title": "UI Intake", "content": content},
    ).get_json()["data"]
    client.post(f"/api/v1/requirements/baselines/{baseline['id']}/submit", headers=admin)
    assert (
        client.post(
            f"/api/v1/requirements/baselines/{baseline['id']}/approve", headers=reviewer
        ).status_code
        == 200
    )
    architecture = client.post(
        "/api/v1/architecture/packages",
        headers=admin,
        json={
            "project_id": project_id,
            "source_baseline_id": baseline["id"],
            "title": "UI Architecture",
            "content": {
                "context": {"goal": "reviewable interface"},
                "components": ["web"],
                "data": ["postgres"],
                "integrations": ["git"],
                "deployment": ["preview"],
                "security": ["auth"],
                "operations": ["audit"],
                "threats": ["secret leakage"],
                "failures": ["preview outage"],
            },
        },
    ).get_json()["data"]
    client.post(f"/api/v1/architecture/packages/{architecture['id']}/submit", headers=admin)
    assert (
        client.post(
            f"/api/v1/architecture/packages/{architecture['id']}/approve", headers=reviewer
        ).status_code
        == 200
    )
    return architecture


def test_mockup_preview_and_acceptance_gate(client, org, auth_headers):
    admin = auth_headers()
    LocalProvider(org.slug).ensure_local_user(
        "phase4-reviewer@test.local", "password123", "Reviewer", ["product_owner"]
    )
    reviewer = _login(client, "phase4-reviewer@test.local", org.slug)
    project = client.post(
        "/api/v1/projects", headers=admin, json={"name": "UI Pilot", "key": "uipil"}
    ).get_json()["data"]
    architecture = _setup_approved_architecture(client, admin, reviewer, project["id"])

    mockup = client.post(
        "/api/v1/design/mockups",
        headers=admin,
        json={
            "project_id": project["id"],
            "source_architecture_id": architecture["id"],
            "title": "Dashboard Mockup",
            "file_id": "penpot-file-1",
            "file_url": "https://penpot.example/#/files/penpot-file-1",
        },
    )
    assert mockup.status_code == 201
    mockup_id = mockup.get_json()["data"]["id"]
    assert mockup.get_json()["data"]["design_reference"]["handoff"]["required"] is True
    assert (
        client.post(f"/api/v1/design/mockups/{mockup_id}/submit", headers=admin).status_code == 200
    )
    assert (
        client.post(f"/api/v1/design/mockups/{mockup_id}/approve", headers=reviewer).status_code
        == 200
    )

    expires = (datetime.utcnow() + timedelta(hours=2)).isoformat()
    preview = client.post(
        "/api/v1/design/previews",
        headers=admin,
        json={
            "mockup_id": mockup_id,
            "commit_sha": "abc123",
            "environment": "preview",
            "url": "https://preview.example/ui/abc123",
            "expires_at": expires,
            "access_policy": {"authentication": "required", "data_class": "synthetic"},
        },
    )
    assert preview.status_code == 201
    preview_id = preview.get_json()["data"]["id"]

    session = client.post(
        "/api/v1/design/acceptance/sessions",
        headers=admin,
        json={
            "preview_id": preview_id,
            "criteria": [{"key": "dashboard-visible", "title": "Dashboard is visible"}],
            "scenario_guidance": ["Open the preview URL"],
        },
    )
    assert session.status_code == 201
    session_id = session.get_json()["data"]["id"]
    assert (
        client.post(
            f"/api/v1/design/acceptance/sessions/{session_id}/results",
            headers=admin,
            json={"criterion_key": "dashboard-visible", "outcome": "pass"},
        ).status_code
        == 201
    )
    completed = client.post(
        f"/api/v1/design/acceptance/sessions/{session_id}/complete", headers=admin, json={}
    )
    assert completed.status_code == 200
    assert completed.get_json()["data"]["status"] == "accepted"


def test_defect_cannot_close_without_regression_evidence(client, auth_headers):
    admin = auth_headers()
    project = client.post(
        "/api/v1/projects", headers=admin, json={"name": "Defect Pilot", "key": "defp"}
    ).get_json()["data"]
    defect = client.post(
        "/api/v1/design/defects",
        headers=admin,
        json={
            "project_id": project["id"],
            "title": "Broken focus order",
            "severity": "high",
            "reproduction_steps": ["Open page", "Tab through controls"],
            "expected": "Focus follows the visual order",
            "actual": "Focus skips the primary action",
        },
    )
    assert defect.status_code == 201
    defect_id = defect.get_json()["data"]["id"]
    blocked = client.patch(
        f"/api/v1/design/defects/{defect_id}", headers=admin, json={"status": "closed"}
    )
    assert blocked.status_code == 409
    closed = client.patch(
        f"/api/v1/design/defects/{defect_id}",
        headers=admin,
        json={"status": "closed", "regression_evidence": {"status": "passed", "command": "pytest"}},
    )
    assert closed.status_code == 200
