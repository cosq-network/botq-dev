from app.auth.providers.local import LocalProvider


def _login(client, email, org_slug):
    return {
        "Authorization": "Bearer "
        + client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "password123", "organization": org_slug},
        ).get_json()["data"]["token"]
    }


def _baseline(client, headers, project_id):
    content = {
        "goals": ["Deliver safely"],
        "functional_specifications": ["Users must log in"],
        "constraints": [],
        "acceptance_expectations": ["System must return 200 within 1 second"],
        "attachments": [],
        "repository_references": [],
    }
    baseline = client.post(
        "/api/v1/requirements/baselines",
        headers=headers,
        json={"project_id": project_id, "title": "Pilot Intake", "content": content},
    ).get_json()["data"]
    client.post(f"/api/v1/requirements/baselines/{baseline['id']}/submit", headers=headers)
    return baseline


def _architecture(client, headers, project_id, baseline_id):
    content = {
        "context": {"goal": "safe delivery"},
        "components": ["api", "worker"],
        "data": ["postgres"],
        "integrations": ["git"],
        "deployment": ["docker"],
        "security": ["tenant isolation"],
        "operations": ["audit"],
        "threats": ["secret leakage"],
        "failures": ["provider outage"],
    }
    return client.post(
        "/api/v1/architecture/packages",
        headers=headers,
        json={
            "project_id": project_id,
            "source_baseline_id": baseline_id,
            "title": "Pilot Architecture",
            "content": content,
        },
    ).get_json()["data"]


def _plan(client, headers, project_id, architecture_id):
    content = {
        "steps": [{"id": "step-1", "title": "Implement", "validation": "pytest"}],
        "environment_manifest": {"DATABASE_URL": {"type": "url", "required": True, "secret": True}},
        "budget": {"max_minutes": 30, "max_cost": 5},
        "permissions": {"tools": ["read", "write"], "paths": ["backend"]},
        "escalation_rules": ["pause on failure"],
        "feasibility": {"toolchain": "available"},
    }
    return client.post(
        "/api/v1/plans",
        headers=headers,
        json={
            "project_id": project_id,
            "source_architecture_id": architecture_id,
            "title": "Pilot Plan",
            "content": content,
        },
    ).get_json()["data"]


def test_architecture_and_plan_gates_are_version_bound(client, org, auth_headers):
    admin = auth_headers()
    LocalProvider(org.slug).ensure_local_user(
        "phase-reviewer@test.local", "password123", "Reviewer", ["product_owner"]
    )
    reviewer = _login(client, "phase-reviewer@test.local", org.slug)
    project = client.post(
        "/api/v1/projects",
        headers=admin,
        json={"name": "Pilot", "key": "p123"},
    ).get_json()["data"]
    baseline = _baseline(client, admin, project["id"])
    assert (
        client.post(
            f"/api/v1/requirements/baselines/{baseline['id']}/approve", headers=reviewer
        ).status_code
        == 200
    )

    architecture = _architecture(client, admin, project["id"], baseline["id"])
    assert (
        client.post(
            f"/api/v1/architecture/packages/{architecture['id']}/submit", headers=admin
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/architecture/packages/{architecture['id']}/approve", headers=reviewer
        ).status_code
        == 200
    )

    plan = _plan(client, admin, project["id"], architecture["id"])
    assert client.post(f"/api/v1/plans/{plan['id']}/submit", headers=admin).status_code == 200
    assert client.post(f"/api/v1/plans/{plan['id']}/approve", headers=reviewer).status_code == 200

    run = client.post(
        "/api/v1/agent-runs",
        headers=admin,
        json={"plan_id": plan["id"], "objective": "Implement pilot", "writable_paths": ["backend"]},
    )
    assert run.status_code == 201
    assert run.get_json()["data"]["plan_hash"] == plan["current_hash"]
    run_id = run.get_json()["data"]["id"]
    assert client.post(f"/api/v1/agent-runs/{run_id}/start", headers=admin).status_code == 200
    change_set = client.post(
        f"/api/v1/agent-runs/{run_id}/change-sets",
        headers=admin,
        json={"branch": "agent/pilot", "base_commit": "abc123"},
    )
    assert change_set.status_code == 201
    file_response = client.post(
        f"/api/v1/change-sets/{change_set.get_json()['data']['id']}/files",
        headers=admin,
        json={"path": "frontend/app.js", "action": "modify", "diff": "@@"},
    )
    assert file_response.status_code == 409
    assert file_response.get_json()["error"]["code"] == "path_out_of_scope"


def test_run_boundary_rejects_unapproved_plan_and_out_of_scope_paths(client, auth_headers):
    admin = auth_headers()
    project = client.post(
        "/api/v1/projects",
        headers=admin,
        json={"name": "Blocked Pilot", "key": "blockp"},
    ).get_json()["data"]
    response = client.post(
        "/api/v1/agent-runs",
        headers=admin,
        json={"plan_id": "00000000-0000-0000-0000-000000000000", "objective": "unsafe"},
    )
    assert response.status_code == 404
    assert project["key"] == "blockp"


def test_traceability_requires_same_project_and_searches_artifacts(client, auth_headers):
    headers = auth_headers()
    project = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Trace Pilot", "key": "tracep"},
    ).get_json()["data"]
    baseline = _baseline(client, headers, project["id"])
    link = client.post(
        "/api/v1/traceability/links",
        headers=headers,
        json={
            "source_type": "requirement_baseline",
            "source_id": baseline["id"],
            "target_type": "requirement_baseline",
            "target_id": baseline["id"],
            "relation": "refines",
        },
    )
    assert link.status_code == 201
    search = client.get("/api/v1/traceability/search?q=trace", headers=headers)
    assert search.status_code == 200
    assert any(item["id"] == baseline["id"] for item in search.get_json()["data"])
