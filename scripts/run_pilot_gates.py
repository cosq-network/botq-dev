"""Execute the repeatable local BotQ pilot workflow through Gate 4.

This script creates a fresh project and records the requirement, architecture,
plan, approvals, and managed-inference agent run through botq's public API. It
does not apply generated changes or claim human acceptance; the worker stops at
a reviewable change set by design. Credentials are read from environment
variables and are never included in the evidence output.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ARCHITECTURE = {
    "context": {"goal": "deliver the BotQ registration and login pilot"},
    "components": ["Flask web application", "PostgreSQL", "botq worker"],
    "data": ["users", "sessions", "audit events"],
    "integrations": ["GitHub SSH repository", "Heroku managed inference"],
    "deployment": ["local Docker Compose"],
    "security": [
        "Argon2id",
        "CSRF",
        "secure sessions",
        "rate limiting",
        "tenant isolation",
    ],
    "operations": ["health checks", "backups", "rollback", "correlation IDs"],
    "threats": ["credential leakage", "provider output", "session abuse"],
    "failures": ["provider outage", "database outage", "failed migration"],
}

PLAN = {
    "steps": [
        {
            "id": "inspect",
            "title": "Inspect the existing BotQ pilot tests",
            "validation": "git status and existing test manifest",
        },
        {
            "id": "implement",
            "title": "Add a focused regression test for successful-login rate-limit reset",
            "validation": "pytest tests/test_auth.py",
        },
        {
            "id": "security",
            "title": "Verify the rate-limit reset regression and existing security controls",
            "validation": "pytest tests/test_auth.py and dependency scan",
        },
    ],
    "environment_manifest": {
        "DATABASE_URL": {"type": "url", "required": True, "secret": True},
        "HEROKU_INFERENCE_BASE_URL": {"type": "url", "required": True, "secret": False},
        "HEROKU_INFERENCE_MODEL": {"type": "string", "required": True, "secret": False},
        "SECRET_KEY": {"type": "string", "required": True, "secret": True},
    },
    "budget": {"max_minutes": 20, "max_cost": 2},
    "permissions": {"tools": ["read", "write"], "paths": ["tests"]},
    "escalation_rules": [
        "pause on provider failure",
        "pause on secret exposure",
        "pause on an out-of-scope path",
    ],
    "feasibility": {
        "toolchain": "Python 3.13, Flask, PostgreSQL, Docker Compose",
        "repository": "GitHub SSH repository synchronized at the approved pilot commit",
        "existing_files": "app/__init__.py, app/models.py, app/auth/routes.py, app/auth/forms.py, tests/test_auth.py",
        "existing_controls": "Argon2id, Flask-WTF CSRF, secure sessions, 12-character passwords, and five-failure rate limiting",
        "validation": "pytest, ruff, compileall, and security baseline",
        "constraints": "Do not add dependencies; do not replace application architecture; only modify tests/test_auth.py; preserve existing test style.",
    },
}


def content(suffix: str) -> dict:
    return {
        "goals": [
            f"Deliver secure registration and login for the BotQ pilot ({suffix})"
        ],
        "functional_specifications": [
            "A user can register with a valid email and password.",
            "A registered user can log in and log out.",
            "Passwords are stored with Argon2id and are never returned by the API.",
            "CSRF, secure session, rate-limit, and tenant-isolation controls are enforced.",
        ],
        "constraints": [
            "Python Flask with PostgreSQL and server-rendered HTML templates.",
            "The pilot runs in local Docker Compose.",
            "Email verification, password reset, MFA, and external preview are out of scope.",
        ],
        "acceptance_expectations": [
            "Registration rejects malformed or weak credentials.",
            "Login succeeds for a valid account and fails safely for invalid credentials.",
            "Logout invalidates the session.",
            "Automated tests and security checks pass against the approved commit.",
        ],
        "attachments": [],
        "repository_references": [],
    }


def _pilot_test_context() -> str:
    """Supply the exact approved test file, rather than a guessed repository map."""
    test_file = Path(__file__).resolve().parents[1] / "pilot-botq-dev" / "tests" / "test_auth.py"
    try:
        source = test_file.read_text(encoding="utf-8")
    except OSError:
        # The run remains safe if the optional local pilot clone is unavailable:
        # the worker will receive a deliberately insufficient snapshot and must
        # fail review rather than invent a repository structure.
        return "Exact tests/test_auth.py source is unavailable; stop without proposing changes."
    regression_test = '''\n\ndef test_successful_login_clears_prior_failed_attempts(client):
    register(client)
    for _ in range(4):
        response = login(client, password="incorrect-password")
        assert b"Invalid email or password" in response.data

    response = login(client)
    assert b"Protected area" in response.data

    client.post("/logout", follow_redirects=True)
    response = login(client, password="incorrect-password")
    assert b"Invalid email or password" in response.data
    assert b"Too many failed attempts" not in response.data
'''
    # Give the model a mechanically generated target rather than asking it to
    # reproduce line numbers or context from memory. botq still verifies the
    # returned diff independently before persisting it.
    target = "".join(
        difflib.unified_diff(
            source.splitlines(keepends=True),
            (source.rstrip() + regression_test + "\n").splitlines(keepends=True),
            fromfile="tests/test_auth.py",
            tofile="tests/test_auth.py",
        )
    )
    return (
        "Approved repository snapshot (tests/test_auth.py, exact current content):\n"
        f"{source}\n\n"
        "Requested single-file change: append one pytest test proving that a successful login clears "
        "prior failed-login attempts. Register a user, make four failed logins, log in successfully, "
        "then make one failed login and assert the normal 'Invalid email or password' response (not "
        "the rate-limit response). Return exactly one modify change for tests/test_auth.py and no other files.\n\n"
        "Required output diff target: return this exact unified diff unchanged (apart from JSON escaping):\n"
        f"{target}"
    )


class Api:
    def __init__(self, base_url: str, email: str, password: str, organization: str):
        self.base_url = base_url.rstrip("/")
        self.organization = organization
        response = requests.post(
            f"{self.base_url}/api/v1/auth/login",
            json={"email": email, "password": password, "organization": organization},
            timeout=30,
        )
        self._check(response, "login")
        self.token = response.json()["data"]["token"]

    def request(self, method: str, path: str, *, expected: int = 200, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.token}"
        response = requests.request(
            method,
            f"{self.base_url}{path}",
            headers=headers,
            timeout=180,
            **kwargs,
        )
        self._check(response, path, expected)
        body = response.json()
        if "data" not in body:
            raise RuntimeError(f"{path}: response has no data envelope")
        return body["data"]

    @staticmethod
    def _check(response: requests.Response, action: str, expected: int = 200):
        if response.status_code != expected:
            detail = response.text[:1000]
            raise RuntimeError(
                f"{action}: expected HTTP {expected}, got {response.status_code}: {detail}"
            )


def run(args: argparse.Namespace) -> dict:
    suffix = datetime.now(timezone.utc).strftime("%m%d%H%M%S")
    admin = Api(args.base_url, args.admin_email, args.admin_password, args.organization)
    reviewer = Api(
        args.base_url, args.reviewer_email, args.reviewer_password, args.organization
    )

    project = admin.request(
        "POST",
        "/api/v1/projects",
        json={"name": f"BotQ Pilot {suffix}", "key": f"botq-{suffix}"},
        expected=201,
    )
    project_id = project["id"]

    baseline = admin.request(
        "POST",
        "/api/v1/requirements/baselines",
        json={
            "project_id": project_id,
            "title": "BotQ Registration and Login Requirements",
            "content": content(suffix),
        },
        expected=201,
    )
    baseline_id = baseline["id"]
    analysis = admin.request(
        "POST", f"/api/v1/requirements/baselines/{baseline_id}/analyze", expected=201
    )
    proposals = admin.request(
        "POST",
        f"/api/v1/requirements/analyses/{analysis['id']}/work-items",
        expected=201,
    )
    admin.request("POST", f"/api/v1/requirements/baselines/{baseline_id}/submit")
    approved_baseline = reviewer.request(
        "POST", f"/api/v1/requirements/baselines/{baseline_id}/approve"
    )

    architecture = admin.request(
        "POST",
        "/api/v1/architecture/packages",
        json={
            "project_id": project_id,
            "source_baseline_id": baseline_id,
            "title": "BotQ Pilot Architecture",
            "content": ARCHITECTURE,
        },
        expected=201,
    )
    architecture_id = architecture["id"]
    admin.request(
        "POST",
        f"/api/v1/architecture/packages/{architecture_id}/adrs",
        json={
            "key": "ADR-BOTQ-001",
            "title": "Use local Flask templates with PostgreSQL",
            "context": "The pilot needs a small auditable web surface.",
            "decision": "Use server-rendered Flask templates backed by PostgreSQL and secure local sessions.",
            "consequences": "The pilot remains simple to operate; richer SPA interactions remain future work.",
        },
        expected=201,
    )
    comment = admin.request(
        "POST",
        f"/api/v1/architecture/packages/{architecture_id}/comments",
        json={
            "body": "Confirm authentication and recovery boundaries.",
            "anchor": {"section": "security"},
        },
        expected=201,
    )
    admin.request("POST", f"/api/v1/architecture/comments/{comment['id']}/resolve")
    admin.request("POST", f"/api/v1/architecture/packages/{architecture_id}/submit")
    approved_architecture = reviewer.request(
        "POST", f"/api/v1/architecture/packages/{architecture_id}/approve"
    )

    plan = admin.request(
        "POST",
        "/api/v1/plans",
        json={
            "project_id": project_id,
            "source_architecture_id": architecture_id,
            "title": "BotQ Pilot Implementation Plan",
            "content": PLAN,
        },
        expected=201,
    )
    plan_id = plan["id"]
    admin.request("POST", f"/api/v1/plans/{plan_id}/submit")
    approved_plan = reviewer.request("POST", f"/api/v1/plans/{plan_id}/approve")

    run_record = admin.request(
        "POST",
        "/api/v1/agent-runs",
        json={
            "plan_id": plan_id,
            "objective": "Add and verify one focused regression test proving a successful login clears prior failed-login attempts.",
            "allowed_tools": ["read", "write"],
            "writable_paths": ["tests"],
            "environment": {
                "branch": f"agent/botq-pilot-{suffix}",
                "base_commit": args.base_commit,
                "repository_snapshot": _pilot_test_context(),
            },
            "model_config": {
                "provider": "heroku",
                "model": "nova-2-lite",
                "max_tokens": 4096,
            },
            "budget": {"max_minutes": 20, "max_cost": 2},
        },
        expected=201,
    )
    run_id = run_record["id"]
    admin.request("POST", f"/api/v1/agent-runs/{run_id}/start")

    deadline = time.monotonic() + args.worker_timeout
    final_run = None
    while time.monotonic() < deadline:
        final_run = admin.request("GET", f"/api/v1/agent-runs/{run_id}")
        if final_run["status"] in {"completed", "failed", "cancelled", "paused"}:
            break
        time.sleep(5)
    if not final_run or final_run["status"] != "completed":
        raise RuntimeError(f"Agent run did not complete successfully: {final_run}")

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "organization": args.organization,
        "project_id": project_id,
        "baseline": {
            "id": baseline_id,
            "version": approved_baseline.get("current_version"),
            "hash": approved_baseline.get("content_hash"),
            "analysis_id": analysis["id"],
            "analysis_provider": analysis.get("provider"),
            "analysis_model": analysis.get("model"),
            "proposal_count": len(proposals),
            "status": approved_baseline.get("status"),
        },
        "architecture": {
            "id": architecture_id,
            "version": approved_architecture.get("current_version"),
            "hash": approved_architecture.get("content_hash"),
            "status": approved_architecture.get("status"),
        },
        "plan": {
            "id": plan_id,
            "version": approved_plan.get("current_version"),
            "hash": approved_plan.get("content_hash"),
            "status": approved_plan.get("status"),
        },
        "agent_run": {
            "id": run_id,
            "status": final_run["status"],
            "attempt_count": final_run.get("attempt_count"),
            "checkpoint_count": final_run.get("checkpoint_count"),
            "events": final_run.get("events", []),
        },
        "worker_contract": "completed at reviewable change-set boundary; no repository branch was modified",
    }
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default=os.environ.get("BOTQ_PILOT_BASE_URL", "http://127.0.0.1:18082"),
    )
    parser.add_argument(
        "--organization", default=os.environ.get("BOTQ_PILOT_ORGANIZATION", "pilot")
    )
    parser.add_argument(
        "--admin-email",
        default=os.environ.get("BOTQ_PILOT_ADMIN_EMAIL", "benoy-admin@example.invalid"),
    )
    parser.add_argument(
        "--reviewer-email",
        default=os.environ.get(
            "BOTQ_PILOT_REVIEWER_EMAIL", "benoy-reviewer@example.invalid"
        ),
    )
    parser.add_argument(
        "--admin-password", default=os.environ.get("BOTQ_PILOT_ADMIN_PASSWORD")
    )
    parser.add_argument(
        "--reviewer-password", default=os.environ.get("BOTQ_PILOT_REVIEWER_PASSWORD")
    )
    parser.add_argument(
        "--base-commit",
        default=os.environ.get(
            "BOTQ_PILOT_BASE_COMMIT", "31cbdb1e31a120c0f90ce2e8c638957e2ba68aeb"
        ),
    )
    parser.add_argument("--worker-timeout", type=int, default=240)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.admin_password or not args.reviewer_password:
        parser.error(
            "admin and reviewer passwords must be supplied through BOTQ_PILOT_*_PASSWORD"
        )
    try:
        report = run(args)
    except (OSError, requests.RequestException, RuntimeError) as exc:
        print(f"pilot gate execution failed: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
