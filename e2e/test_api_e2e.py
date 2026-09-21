import os
from datetime import UTC, datetime, timedelta

import pytest
import requests

ARCHITECTURE_CONTENT = {
    "context": {"goal": "deliver an auditable pilot"},
    "components": ["api", "worker"],
    "data": ["postgres"],
    "integrations": ["git", "inference"],
    "deployment": ["docker"],
    "security": ["tenant isolation", "secret masking"],
    "operations": ["audit", "health checks"],
    "threats": ["provider output", "credential leakage"],
    "failures": ["provider outage", "preview outage"],
}

PLAN_CONTENT = {
    "steps": [{"id": "implement", "title": "Implement pilot", "validation": "pytest"}],
    "environment_manifest": {},
    "budget": {"max_minutes": 10, "max_cost": 1},
    "permissions": {"tools": ["read", "write"], "paths": ["backend"]},
    "escalation_rules": ["pause on provider failure"],
    "feasibility": {"toolchain": "available"},
}


def _content(suffix):
    return {
        "goals": [f"Deliver the E2E pilot {suffix}"],
        "functional_specifications": [
            "The API must return a successful health response"
        ],
        "constraints": ["The test environment must not call external inference"],
        "acceptance_expectations": ["The health endpoint returns status 200"],
        "attachments": [],
        "repository_references": [],
    }


@pytest.fixture(scope="module")
def workflow(admin, reviewer, unique_suffix):
    project = admin.data(
        "POST",
        "/api/v1/projects",
        json={"name": f"E2E Pilot {unique_suffix}", "key": f"e2e-{unique_suffix}"},
    )
    project_id = project["id"]

    baseline = admin.data(
        "POST",
        "/api/v1/requirements/baselines",
        json={
            "project_id": project_id,
            "title": "E2E Requirements",
            "content": _content(unique_suffix),
        },
    )
    baseline_id = baseline["id"]
    admin.request(
        "POST",
        f"/api/v1/requirements/baselines/{baseline_id}/versions",
        json={"content": baseline["content"]},
        expected=409,
    )
    admin.data("GET", "/api/v1/requirements/baselines")
    admin.data("GET", f"/api/v1/requirements/baselines/{baseline_id}")
    admin.data("GET", f"/api/v1/requirements/baselines/{baseline_id}/versions")
    admin.data("GET", f"/api/v1/requirements/baselines/{baseline_id}/versions/1")
    admin.data("GET", f"/api/v1/requirements/baselines/{baseline_id}/versions/1/diff")
    analysis = admin.data(
        "POST", f"/api/v1/requirements/baselines/{baseline_id}/analyze"
    )
    analysis_id = analysis["id"]
    admin.data("GET", f"/api/v1/requirements/baselines/{baseline_id}/analyses")
    admin.data("GET", f"/api/v1/requirements/analyses/{analysis_id}")
    generated = admin.data(
        "POST", f"/api/v1/requirements/analyses/{analysis_id}/work-items"
    )
    admin.data("POST", f"/api/v1/requirements/baselines/{baseline_id}/submit")
    # The reviewer is intentionally the only actor taking the gate decision.
    reviewer.data("POST", f"/api/v1/requirements/baselines/{baseline_id}/approve")

    architecture = admin.data(
        "POST",
        "/api/v1/architecture/packages",
        json={
            "project_id": project_id,
            "source_baseline_id": baseline_id,
            "title": "E2E Architecture",
            "content": ARCHITECTURE_CONTENT,
        },
    )
    architecture_id = architecture["id"]
    admin.data("GET", "/api/v1/architecture/packages")
    admin.data("GET", f"/api/v1/architecture/packages/{architecture_id}")
    admin.data(
        "POST",
        f"/api/v1/architecture/packages/{architecture_id}/adrs",
        json={
            "key": "ADR-E2E",
            "title": "Use deterministic E2E providers",
            "context": "The suite must be repeatable.",
            "decision": "Use rules analysis and disabled implementation workers.",
            "consequences": "Managed providers are tested separately.",
        },
    )
    comment = admin.data(
        "POST",
        f"/api/v1/architecture/packages/{architecture_id}/comments",
        json={
            "body": "Please confirm the provider boundary.",
            "anchor": {"section": "integrations"},
        },
    )
    admin.data("POST", f"/api/v1/architecture/comments/{comment['id']}/resolve")
    admin.data("POST", f"/api/v1/architecture/packages/{architecture_id}/submit")
    reviewer.data("POST", f"/api/v1/architecture/packages/{architecture_id}/approve")
    admin.request(
        "POST",
        f"/api/v1/architecture/packages/{architecture_id}/versions",
        json={"content": architecture["content"]},
        expected=409,
    )
    for action in ("request-changes", "reject", "waive"):
        admin.request(
            "POST",
            f"/api/v1/architecture/packages/{architecture_id}/{action}",
            json={},
            expected=409,
        )

    plan = admin.data(
        "POST",
        "/api/v1/plans",
        json={
            "project_id": project_id,
            "source_architecture_id": architecture_id,
            "title": "E2E Technical Plan",
            "content": PLAN_CONTENT,
        },
    )
    plan_id = plan["id"]
    admin.data("GET", "/api/v1/plans")
    admin.data("GET", f"/api/v1/plans/{plan_id}")
    admin.data("POST", f"/api/v1/plans/{plan_id}/submit")
    reviewer.data("POST", f"/api/v1/plans/{plan_id}/approve")
    admin.request(
        "POST",
        f"/api/v1/plans/{plan_id}/versions",
        json={"content": plan["content"]},
        expected=409,
    )
    for action in ("request-changes", "reject"):
        admin.request(
            "POST", f"/api/v1/plans/{plan_id}/{action}", json={}, expected=409
        )

    run = admin.data(
        "POST",
        "/api/v1/agent-runs",
        json={
            "plan_id": plan_id,
            "objective": "Exercise the controlled agent boundary",
            "allowed_tools": ["read"],
            "writable_paths": ["backend"],
            "environment": {"branch": "agent/e2e"},
        },
    )
    run_id = run["id"]
    admin.data("GET", "/api/v1/agent-runs")
    admin.data("GET", f"/api/v1/agent-runs/{run_id}")
    admin.data("POST", f"/api/v1/agent-runs/{run_id}/start")
    admin.data(
        "POST",
        f"/api/v1/agent-runs/{run_id}/checkpoints",
        json={"state": {"step": "implement"}, "evidence": {"source": "e2e"}},
    )

    change_set = admin.data(
        "POST",
        f"/api/v1/agent-runs/{run_id}/change-sets",
        json={"branch": "agent/e2e", "base_commit": "e2e-base"},
    )
    change_set_id = change_set["id"]
    admin.data(
        "POST",
        f"/api/v1/change-sets/{change_set_id}/files",
        json={
            "path": "backend/e2e.py",
            "action": "add",
            "diff": "+def e2e():\n+    return True\n",
        },
    )
    reviewed = admin.data(
        "POST",
        f"/api/v1/change-sets/{change_set_id}/self-review",
        json={"review": {"result": "Reviewed deterministic E2E change."}},
    )
    verification = admin.data(
        "POST",
        f"/api/v1/change-sets/{change_set_id}/verifications",
        json={
            "kind": "test",
            "command": "pytest e2e",
            "status": "passed",
            "result": {"change_set_hash": reviewed["diff_hash"], "passed": True},
        },
    )
    assert verification["change_set_hash"] == reviewed["diff_hash"]
    admin.data("POST", f"/api/v1/change-sets/{change_set_id}/submit")
    reviewer.data("POST", f"/api/v1/change-sets/{change_set_id}/approve")
    admin.data("GET", "/api/v1/approvals")
    admin.data("GET", f"/api/v1/approvals/artifact/change_set/{change_set_id}")

    work_item = next(
        (item for item in generated if item["kind"] == "feature"), generated[0]
    )
    return {
        "project": project,
        "baseline": baseline,
        "analysis": analysis,
        "architecture": architecture,
        "plan": plan,
        "run": run,
        "change_set": change_set,
        "work_item": work_item,
    }


def test_auth_health_and_organization_apis(e2e_base_url, admin):
    assert admin.data("GET", "/api/v1/auth/providers")
    bootstrap_headers = {"X-Bootstrap-Token": "e2e-bootstrap-token"}
    admin.request(
        "GET", "/api/v1/organizations", headers=bootstrap_headers, expected=200
    )
    admin.request(
        "POST",
        "/api/v1/organizations",
        headers=bootstrap_headers,
        json={"name": "E2E Secondary Organization", "slug": "e2e-secondary"},
        expected=201,
    )
    me = admin.data("GET", "/api/v1/auth/me")
    assert me["organization"]["slug"] == "acme"
    assert admin.data("GET", "/api/v1/organizations/me")
    assert admin.data("GET", "/api/v1/organizations/me/roles")
    assert admin.data("GET", "/api/v1/organizations/me/users")
    admin.data("GET", "/api/v1/projects")
    assert admin.data("GET", "/api/v1/ping")["service"] == "botq"
    assert admin.data("GET", "/health/live")["status"] == "ok"
    assert admin.data("GET", "/health/ready")["status"] == "ready"
    assert admin.data("GET", "/health/metrics")
    metrics = admin.request("GET", "/health/metrics/prometheus", expected=200).text
    assert "http_requests_total" in metrics

    login = requests.post(
        f"{e2e_base_url}/api/v1/auth/login",
        json={
            "email": os.environ.get("BOTQ_E2E_ADMIN_EMAIL", "admin@acme.local"),
            "password": os.environ.get("BOTQ_E2E_PASSWORD", "E2ePass!2026"),
            "organization": os.environ.get("BOTQ_E2E_ORG", "acme"),
        },
        timeout=30,
    )
    assert login.status_code == 200, login.text
    logout_headers = {"Authorization": f"Bearer {login.json()['data']['token']}"}
    admin.request("POST", "/api/v1/auth/logout", headers=logout_headers, expected=200)
    admin.request("GET", "/api/v1/auth/me", headers=logout_headers, expected=401)


def test_requirements_work_items_and_traceability_apis(admin, workflow):
    project_id = workflow["project"]["id"]
    baseline_id = workflow["baseline"]["id"]
    parent = admin.data(
        "POST",
        "/api/v1/work-items",
        json={
            "project_id": project_id,
            "kind": "epic",
            "title": "E2E manually managed epic",
            "source_baseline_id": baseline_id,
        },
    )
    child = admin.data(
        "POST",
        "/api/v1/work-items",
        json={
            "project_id": project_id,
            "kind": "feature",
            "parent_id": parent["id"],
            "title": "E2E manually managed feature",
            "source_baseline_id": baseline_id,
        },
    )
    admin.data("GET", f"/api/v1/work-items?project_id={project_id}")
    admin.data("GET", f"/api/v1/work-items/tree?project_id={project_id}")
    admin.data("GET", f"/api/v1/work-items/{child['id']}")
    admin.data("PATCH", f"/api/v1/work-items/{child['id']}", json={"status": "ready"})
    admin.data(
        "POST",
        f"/api/v1/work-items/{child['id']}/dependencies",
        json={"depends_on_id": parent["id"]},
    )
    admin.data("GET", f"/api/v1/work-items/{child['id']}/dependencies")
    admin.data(
        "DELETE", f"/api/v1/work-items/{child['id']}/dependencies/{parent['id']}"
    )

    link = admin.data(
        "POST",
        "/api/v1/traceability/links",
        json={
            "source_type": "requirement_baseline",
            "source_id": baseline_id,
            "target_type": "architecture",
            "target_id": workflow["architecture"]["id"],
            "relation": "realized-by",
        },
    )
    admin.data("GET", "/api/v1/traceability/links")
    admin.data("GET", "/api/v1/traceability/search?q=E2E")
    admin.data("DELETE", f"/api/v1/traceability/links/{link['id']}")
    admin.data("DELETE", f"/api/v1/work-items/{child['id']}")
    admin.data("DELETE", f"/api/v1/work-items/{parent['id']}")


def test_requirement_decision_version_finding_and_direct_approval_apis(
    admin, reviewer, workflow, unique_suffix
):
    project_id = workflow["project"]["id"]

    versioned = admin.data(
        "POST",
        "/api/v1/requirements/baselines",
        json={
            "project_id": project_id,
            "title": f"E2E Versioned Requirements {unique_suffix}",
            "content": _content(f"versioned-{unique_suffix}"),
        },
    )
    admin.data(
        "POST",
        f"/api/v1/requirements/baselines/{versioned['id']}/versions",
        json={
            "content": {
                **versioned["content"],
                "goals": [f"Deliver the revised E2E pilot {unique_suffix}"],
            },
            "change_summary": "E2E version transition",
        },
    )
    admin.data("GET", f"/api/v1/requirements/baselines/{versioned['id']}/versions/2")
    admin.data(
        "GET", f"/api/v1/requirements/baselines/{versioned['id']}/versions/1/diff?to=2"
    )

    for index, action in enumerate(("reject", "request-changes", "waive")):
        baseline = admin.data(
            "POST",
            "/api/v1/requirements/baselines",
            json={
                "project_id": project_id,
                "title": f"E2E Decision {action} {unique_suffix}-{index}",
                "content": _content(f"decision-{action}-{unique_suffix}"),
            },
        )
        admin.data("POST", f"/api/v1/requirements/baselines/{baseline['id']}/submit")
        decision_payload = {}
        if action == "waive":
            decision_payload = {
                "reason": "Accepted as a documented pilot exception",
                "expires_at": (
                    datetime.now(UTC) + timedelta(days=1)
                ).isoformat(),
            }
        reviewer.data(
            "POST",
            f"/api/v1/requirements/baselines/{baseline['id']}/{action}",
            json=decision_payload,
        )

    cancelled = admin.data(
        "POST",
        "/api/v1/requirements/baselines",
        json={
            "project_id": project_id,
            "title": f"E2E Cancelled Requirements {unique_suffix}",
            "content": _content(f"cancelled-{unique_suffix}"),
        },
    )
    admin.data("POST", f"/api/v1/requirements/baselines/{cancelled['id']}/cancel")

    direct = admin.data(
        "POST",
        "/api/v1/requirements/baselines",
        json={
            "project_id": project_id,
            "title": f"E2E Direct Approval {unique_suffix}",
            "content": _content(f"direct-{unique_suffix}"),
        },
    )
    direct_approval = admin.data(
        "POST",
        "/api/v1/approvals",
        json={
            "artifact_type": "requirement_baseline",
            "artifact_id": direct["id"],
            "decision": "cancelled",
        },
    )
    assert direct_approval["decision"] == "cancelled"

    finding_baseline = admin.data(
        "POST",
        "/api/v1/requirements/baselines",
        json={
            "project_id": project_id,
            "title": f"E2E Finding Requirements {unique_suffix}",
            "content": {
                **_content(f"finding-{unique_suffix}"),
                "functional_specifications": [
                    "The user-friendly interface must return status 200"
                ],
            },
        },
    )
    finding_analysis = admin.data(
        "POST", f"/api/v1/requirements/baselines/{finding_baseline['id']}/analyze"
    )
    finding = next(
        item for item in finding_analysis["findings"] if item["status"] == "open"
    )
    resolved = admin.data(
        "POST",
        f"/api/v1/requirements/analyses/{finding_analysis['id']}/findings/{finding['id']}/resolve",
        json={
            "status": "resolved",
            "reason": "Addressed in the pilot acceptance wording",
        },
    )
    assert resolved["status"] == "resolved"


def test_design_preview_acceptance_and_defect_apis(admin, reviewer, workflow):
    project_id = workflow["project"]["id"]
    mockup = admin.data(
        "POST",
        "/api/v1/design/mockups",
        json={
            "project_id": project_id,
            "source_architecture_id": workflow["architecture"]["id"],
            "title": "E2E Mockup",
            "file_id": "e2e-file",
            "file_url": "https://penpot.example/#/files/e2e-file",
        },
    )
    mockup_id = mockup["id"]
    admin.data("GET", "/api/v1/design/mockups")
    admin.data("GET", f"/api/v1/design/mockups/{mockup_id}")
    admin.data(
        "POST",
        f"/api/v1/design/mockups/{mockup_id}/versions",
        json={"content": {"pages": ["dashboard"], "nodes": ["primary-action"]}},
    )
    comment = admin.data(
        "POST",
        f"/api/v1/design/mockups/{mockup_id}/comments",
        json={
            "body": "Confirm the primary action.",
            "anchor": {"node": "primary-action"},
        },
    )
    admin.data(
        "POST", f"/api/v1/design/mockups/{mockup_id}/comments/{comment['id']}/resolve"
    )
    admin.data(
        "POST",
        f"/api/v1/design/mockups/{mockup_id}/links",
        json={"work_item_id": workflow["work_item"]["id"], "node_id": "primary-action"},
    )
    admin.data("POST", f"/api/v1/design/mockups/{mockup_id}/submit")
    reviewer.data("POST", f"/api/v1/design/mockups/{mockup_id}/approve")
    admin.request(
        "POST",
        f"/api/v1/design/mockups/{mockup_id}/request-changes",
        json={},
        expected=409,
    )
    admin.data("GET", f"/api/v1/design/mockups/{mockup_id}/preview")

    expires = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    preview = admin.data(
        "POST",
        "/api/v1/design/previews",
        json={
            "mockup_id": mockup_id,
            "change_set_id": workflow["change_set"]["id"],
            "commit_sha": "e2e-commit",
            "environment": "preview",
            "url": "https://preview.example/e2e",
            "expires_at": expires,
            "access_policy": {"authentication": "required", "data_class": "synthetic"},
        },
    )
    admin.data("GET", "/api/v1/design/previews")
    admin.data("GET", f"/api/v1/design/previews/{preview['id']}")
    session = admin.data(
        "POST",
        "/api/v1/design/acceptance/sessions",
        json={
            "preview_id": preview["id"],
            "criteria": [{"key": "healthy", "title": "Health is visible"}],
            "scenario_guidance": ["Open the preview"],
        },
    )
    admin.data("GET", f"/api/v1/design/acceptance/sessions/{session['id']}")
    admin.data(
        "POST",
        f"/api/v1/design/acceptance/sessions/{session['id']}/results",
        json={"criterion_key": "healthy", "outcome": "pass"},
    )
    accepted = admin.data(
        "POST", f"/api/v1/design/acceptance/sessions/{session['id']}/complete", json={}
    )
    assert accepted["status"] == "accepted"

    defect = admin.data(
        "POST",
        "/api/v1/design/defects",
        json={
            "project_id": project_id,
            "title": "E2E defect",
            "severity": "medium",
            "reproduction_steps": ["Open preview"],
            "expected": "Focus is visible",
            "actual": "Focus is delayed",
        },
    )
    admin.data("GET", "/api/v1/design/defects")
    admin.data(
        "PATCH",
        f"/api/v1/design/defects/{defect['id']}",
        json={
            "status": "closed",
            "regression_evidence": {"status": "passed", "command": "pytest e2e"},
        },
    )
    admin.data("POST", f"/api/v1/design/previews/{preview['id']}/revoke")


def test_release_deployment_and_approval_apis(admin, reviewer, workflow):
    release = admin.data(
        "POST",
        "/api/v1/releases",
        json={
            "change_set_id": workflow["change_set"]["id"],
            "version": "1.0.0-e2e",
            "commit_sha": "e2e-commit",
            "release_notes": "E2E release",
            "rollback": {
                "previous_deployable_version": "0.9.0",
                "instructions": "restore previous package",
            },
        },
    )
    release_id = release["id"]
    admin.data("GET", "/api/v1/releases")
    admin.data("GET", f"/api/v1/releases/{release_id}")
    admin.data("POST", f"/api/v1/releases/{release_id}/readiness", json={})
    reviewer.data("POST", f"/api/v1/releases/{release_id}/approve")
    packaged = admin.data("POST", f"/api/v1/releases/{release_id}/package")
    assert packaged["status"] == "packaged"

    plan = admin.data(
        "POST",
        "/api/v1/deployment-plans",
        json={
            "release_id": release_id,
            "environment": "staging",
            "content": {
                "prechecks": ["verify package"],
                "migrations": ["none"],
                "deployment_steps": ["deploy"],
                "health_checks": ["GET /health/ready"],
                "rollback_triggers": ["health failure"],
                "recovery_steps": ["restore previous"],
            },
        },
    )
    plan_id = plan["id"]
    admin.data("GET", "/api/v1/deployment-plans")
    admin.data("GET", f"/api/v1/deployment-plans/{plan_id}")
    admin.data("POST", f"/api/v1/deployment-plans/{plan_id}/submit")
    reviewer.data("POST", f"/api/v1/deployment-plans/{plan_id}/approve")
    deployment = admin.data(
        "POST",
        "/api/v1/deployments",
        json={"deployment_plan_id": plan_id, "execute": False},
    )
    admin.data("GET", "/api/v1/deployments")
    admin.data("GET", f"/api/v1/deployments/{deployment['id']}")
    admin.request(
        "POST",
        f"/api/v1/deployments/{deployment['id']}/rollback",
        json={},
        expected=409,
    )


def test_secrets_audit_diagnostics_and_sandbox_apis(admin, workflow):
    secret = admin.data(
        "POST",
        "/api/v1/secrets",
        json={"name": "e2e-secret", "value": "not-returned", "purpose": "test"},
    )
    admin.data("GET", "/api/v1/secrets")
    admin.data("GET", f"/api/v1/secrets/{secret['id']}")
    admin.data(
        "POST", f"/api/v1/secrets/{secret['id']}/rotate", json={"value": "rotated"}
    )
    verified = admin.data("POST", f"/api/v1/secrets/{secret['id']}/verify")
    assert verified["verified"] is True
    admin.data("POST", f"/api/v1/secrets/{secret['id']}/revoke")

    assert admin.data("GET", "/api/v1/audit/events")["total"] > 0
    assert admin.data("GET", "/api/v1/audit/verify")["verified"] is True
    assert admin.data("GET", "/api/v1/audit/export")["count"] > 0
    assert admin.data("GET", "/api/v1/diagnostics/bundle")
    assert admin.data("GET", "/api/v1/diagnostics/retention-plan")
    dry_run = admin.data("POST", "/api/v1/diagnostics/retention/execute", json={})
    assert dry_run["mode"] == "dry_run"
    admin.request(
        "POST",
        "/api/v1/diagnostics/retention/execute",
        json={"dry_run": False},
        expected=403,
    )
    assert admin.data("GET", "/api/v1/sandbox/readiness")
    admin.request(
        "POST",
        "/api/v1/sandbox/runs",
        json={"image": "not-allowed", "command": "true"},
        expected=403,
    )
    admin.request(
        "POST",
        "/api/v1/sandbox/diagnostic",
        json={"image": "not-allowed"},
        expected=(409, 403),
    )
    admin.request(
        "POST",
        "/api/v1/sandbox/probe",
        json={"image": "not-allowed", "command": "true"},
        expected=(409, 403),
    )


def test_api_only_lifecycle_closes_all_seven_gates(admin, e2e_base_url, unique_suffix):
    project = admin.data(
        "POST",
        "/api/v1/projects",
        json={"name": f"API Gate Pilot {unique_suffix}", "key": f"gate-{unique_suffix}"},
    )
    project_id = project["id"]
    admin.data(
        "PATCH",
        f"/api/v1/projects/{project_id}/gate-policy",
        json={
            "approval_mode": "api_automation",
            "require_gate_decisions": True,
            "require_project_responsibility_assignment": False,
            "require_previous_gate_closed": True,
            "auto_sync_evidence": True,
        },
    )
    email = f"gatebot-{unique_suffix}@acme.local"
    password = "GateBot-E2E-2026!"
    admin.data(
        "POST",
        "/api/v1/organizations/me/users",
        json={
            "email": email,
            "display_name": "E2E Gate Automation",
            "password": password,
            "roles": ["gate_automation"],
            "user_type": "automation",
        },
    )
    login_response = requests.post(
        f"{e2e_base_url}/api/v1/auth/login",
        json={
            "email": email,
            "password": password,
            "organization": os.environ.get("BOTQ_E2E_ORG", "acme"),
        },
        timeout=30,
    )
    assert login_response.status_code == 200, login_response.text
    automation = type(admin)(e2e_base_url, login_response.json()["data"]["token"])

    for gate_number in range(1, 8):
        base = f"/api/v1/projects/{project_id}/gates/{gate_number}"
        admin.data("POST", f"{base}/sync")
        gate = admin.data("GET", base)
        for key in gate["required_evidence"]:
            admin.data(
                "POST",
                f"{base}/evidence",
                json={
                    "key": key,
                    "status": "passed",
                    "source": "e2e-api-contract",
                    "command": f"e2e verify {key}",
                    "content_hash": (f"{gate_number}:{key}").encode().hex().ljust(64, "0")[:64],
                    "evidence": {"gate": gate_number, "check": key, "result": "passed"},
                },
            )
        evaluated = admin.data("POST", f"{base}/evaluate")
        assert evaluated["blocking_checks"] == []
        automation.data(
            "POST",
            f"{base}/auto-approve",
            json={"idempotency_key": f"e2e-{unique_suffix}-gate-{gate_number}"},
        )
        closed = automation.data("POST", f"{base}/close")
        assert closed["status"] == "closed"

    summary = admin.data("GET", f"/api/v1/projects/{project_id}/gates/summary")
    assert summary["overall_status"] == "closed"
    assert summary["closed_gates"] == [1, 2, 3, 4, 5, 6, 7]
    assert summary["blocking_checks"] == []
    assert summary["audit_chain_verified"] is True


def test_repository_routes_are_safe_without_external_git(admin, workflow):
    project_id = workflow["project"]["id"]
    admin.request("GET", f"/api/v1/projects/{project_id}/repository", expected=200)
    admin.request(
        "POST", f"/api/v1/projects/{project_id}/repository/test", json={}, expected=404
    )
    admin.request(
        "POST",
        f"/api/v1/projects/{project_id}/repository/rotate-key",
        json={},
        expected=404,
    )
    admin.request(
        "POST",
        f"/api/v1/projects/{project_id}/repository/revoke",
        json={},
        expected=404,
    )
    admin.request(
        "POST", f"/api/v1/projects/{project_id}/repository/sync", json={}, expected=404
    )
    failed = admin.request(
        "POST",
        f"/api/v1/projects/{project_id}/repository",
        json={"ssh_url": "git@unconfigured.example:org/repo.git"},
        expected=409,
    )
    assert failed.json()["error"]["code"] == "key_provision_failed"


def test_agent_run_pause_cancel_and_project_mutation_apis(admin, workflow):
    run_id = workflow["run"]["id"]
    admin.data(
        "POST",
        f"/api/v1/agent-runs/{run_id}/pause",
        json={"reason": "E2E control test"},
    )
    admin.data("POST", f"/api/v1/agent-runs/{run_id}/start")
    admin.data("POST", f"/api/v1/agent-runs/{run_id}/cancel")
    project_id = workflow["project"]["id"]
    admin.data("GET", f"/api/v1/projects/{project_id}")
    admin.data(
        "PATCH",
        f"/api/v1/projects/{project_id}",
        json={"description": "updated by E2E"},
    )
    archived = admin.data("POST", f"/api/v1/projects/{project_id}/archive")
    assert archived["archived"] is True


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/api/v1/auth/oidc/login", 401),
        ("GET", "/api/v1/auth/oidc/callback", 401),
    ],
)
def test_disabled_oidc_endpoints_fail_closed(admin, method, path, expected):
    admin.request(method, path, expected=expected)
