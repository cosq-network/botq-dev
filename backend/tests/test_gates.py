def _project(client, headers):
    response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Gate Project", "key": "gate-project"},
    )
    return response.get_json()["data"]


def test_gate_lifecycle_exposes_evidence_evaluation_decision_and_close(client, auth_headers):
    project = _project(client, auth_headers())
    base = f"/api/v1/projects/{project['id']}/gates/1"

    listed = client.get(f"/api/v1/projects/{project['id']}/gates", headers=auth_headers())
    assert listed.status_code == 200
    assert len(listed.get_json()["data"]) == 7

    gate = client.get(base, headers=auth_headers()).get_json()["data"]
    for key in gate["required_evidence"]:
        response = client.post(
            f"{base}/evidence",
            headers=auth_headers(),
            json={"key": key, "status": "passed", "detail": "verified", "evidence": {"source": "test"}},
        )
        assert response.status_code == 201

    evaluated = client.post(f"{base}/evaluate", headers=auth_headers())
    assert evaluated.status_code == 200
    assert evaluated.get_json()["data"]["missing_decisions"] == ["organization_administrator"]

    decision = client.post(
        f"{base}/decisions",
        headers=auth_headers(),
        json={"responsibility_type": "organization_administrator", "decision": "approved"},
    )
    assert decision.status_code == 201

    closed = client.post(f"{base}/close", headers=auth_headers())
    assert closed.status_code == 200
    assert closed.get_json()["data"]["status"] == "closed"

    reopened = client.post(f"{base}/reopen", headers=auth_headers(), json={"reason": "new evidence"})
    assert reopened.status_code == 200
    assert reopened.get_json()["data"]["status"] == "open"


def test_gate_close_reports_missing_evidence(client, auth_headers):
    project = _project(client, auth_headers())
    response = client.post(
        f"/api/v1/projects/{project['id']}/gates/2/close", headers=auth_headers()
    )
    assert response.status_code == 409
    assert "blocking_evidence" in response.get_json()["error"]["details"]


def test_api_automation_policy_auto_approve_and_summary(client, auth_headers, login):
    project = _project(client, auth_headers())
    policy = client.patch(
        f"/api/v1/projects/{project['id']}/gate-policy",
        headers=auth_headers(),
        json={
            "approval_mode": "api_automation",
            "require_project_responsibility_assignment": False,
        },
    )
    assert policy.status_code == 200
    assert policy.get_json()["data"]["approval_mode"] == "api_automation"

    created = client.post(
        "/api/v1/organizations/me/users",
        headers=auth_headers(),
        json={
            "email": "gatebot@example.test",
            "display_name": "Gate Bot",
            "password": "correct-horse-battery-34",
            "roles": ["gate_automation"],
            "user_type": "automation",
        },
    )
    assert created.status_code == 201
    assert created.get_json()["data"]["user_type"] == "automation"
    bot_token = login("gatebot@example.test", "correct-horse-battery-34")

    base = f"/api/v1/projects/{project['id']}/gates/1"
    gate = client.get(base, headers=auth_headers()).get_json()["data"]
    for key in gate["required_evidence"]:
        response = client.post(
            f"{base}/evidence",
            headers=auth_headers(),
            json={"key": key, "status": "passed", "evidence": {"source": "synthetic-valid"}},
        )
        assert response.status_code == 201

    approved = client.post(
        f"{base}/auto-approve",
        headers=auth_headers(bot_token),
        json={"idempotency_key": "gate-1-auto"},
    )
    assert approved.status_code == 201
    decision = approved.get_json()["data"]["decisions"][0]
    assert decision["decider_type"] == "automation"
    assert decision["approval_mode"] == "api_automation"

    closed = client.post(f"{base}/close", headers=auth_headers(bot_token))
    assert closed.status_code == 200
    summary = client.get(f"/api/v1/projects/{project['id']}/gates/summary", headers=auth_headers())
    assert summary.status_code == 200
    assert summary.get_json()["data"]["closed_gates"] == [1]


def test_api_automation_can_close_all_seven_gates_with_submitted_evidence(
    client, auth_headers, login
):
    project = _project(client, auth_headers())
    policy = client.patch(
        f"/api/v1/projects/{project['id']}/gate-policy",
        headers=auth_headers(),
        json={
            "approval_mode": "api_automation",
            "require_project_responsibility_assignment": False,
            "require_previous_gate_closed": True,
        },
    )
    assert policy.status_code == 200

    created = client.post(
        "/api/v1/organizations/me/users",
        headers=auth_headers(),
        json={
            "email": "all-gates-bot@example.test",
            "display_name": "All Gates Bot",
            "password": "correct-horse-battery-56",
            "roles": ["gate_automation"],
            "user_type": "automation",
        },
    )
    assert created.status_code == 201
    bot_token = login("all-gates-bot@example.test", "correct-horse-battery-56")

    for gate_number in range(1, 8):
        base = f"/api/v1/projects/{project['id']}/gates/{gate_number}"
        gate = client.get(base, headers=auth_headers()).get_json()["data"]
        for key in gate["required_evidence"]:
            evidence = client.post(
                f"{base}/evidence",
                headers={
                    **auth_headers(),
                    "Idempotency-Key": f"gate-{gate_number}-{key}",
                },
                json={
                    "key": key,
                    "status": "passed",
                    "source": "api-only-EXAMPLE-test",
                    "command": f"verify {key}",
                    "content_hash": f"{gate_number:02d}{len(key):02d}".ljust(64, "a"),
                    "evidence": {
                        "gate": gate_number,
                        "check": key,
                        "result": "passed",
                    },
                },
            )
            assert evidence.status_code == 201

        evaluated = client.post(f"{base}/evaluate", headers=auth_headers())
        assert evaluated.status_code == 200
        assert evaluated.get_json()["data"]["blocking_checks"] == []

        approved = client.post(
            f"{base}/auto-approve",
            headers=auth_headers(bot_token),
            json={"idempotency_key": f"gate-{gate_number}-approval"},
        )
        assert approved.status_code == 201
        assert all(
            item["decider_type"] == "automation"
            for item in approved.get_json()["data"]["decisions"]
        )

        closed = client.post(f"{base}/close", headers=auth_headers(bot_token))
        assert closed.status_code == 200
        assert closed.get_json()["data"]["status"] == "closed"

    summary = client.get(f"/api/v1/projects/{project['id']}/gates/summary", headers=auth_headers())
    assert summary.status_code == 200
    payload = summary.get_json()["data"]
    assert payload["overall_status"] == "closed"
    assert payload["closed_gates"] == [1, 2, 3, 4, 5, 6, 7]
    assert payload["open_gates"] == []
    assert payload["blocking_checks"] == []
    assert payload["approval_mode"] == "api_automation"


def test_gate_automation_role_is_least_privilege(client, auth_headers, login):
    project = _project(client, auth_headers())
    policy = client.patch(
        f"/api/v1/projects/{project['id']}/gate-policy",
        headers=auth_headers(),
        json={
            "approval_mode": "api_automation",
            "require_project_responsibility_assignment": False,
        },
    )
    assert policy.status_code == 200

    created = client.post(
        "/api/v1/organizations/me/users",
        headers=auth_headers(),
        json={
            "email": "least-privilege-gatebot@example.test",
            "display_name": "Least Privilege Gate Bot",
            "password": "correct-horse-battery-78",
            "roles": ["gate_automation"],
            "user_type": "automation",
        },
    )
    assert created.status_code == 201
    bot_token = login("least-privilege-gatebot@example.test", "correct-horse-battery-78")

    me = client.get("/api/v1/auth/me", headers=auth_headers(bot_token))
    assert me.status_code == 200
    scopes = set(me.get_json()["data"]["scopes"])
    assert scopes == {"project:read", "gate:approve", "gate:close"}
    assert "admin" not in scopes
    assert "secret:manage" not in scopes
    assert "config:manage" not in scopes

    denied = client.get("/api/v1/secrets", headers=auth_headers(bot_token))
    assert denied.status_code in (401, 403)
