import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.auth.providers.local import LocalProvider
from app.errors import ValidationError
from app.planning.executor import (
    AgentExecutionError,
    ExecutionResult,
    GeneratedChange,
    ManagedInferenceAgentExecutor,
    _implementation_prompt,
    parse_execution_result,
    validate_diff_against_snapshot,
)
from app.planning.worker import AgentRunWorker
from app.requirements.analysis import configured_analyzer


def test_implementation_provider_output_is_strictly_schema_validated():
    result = parse_execution_result(
        {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"changes":[{"path":"backend/app.py","action":"modify",'
                            '"diff":"@@"}],"self_review":{"result":"reviewed"},'
                            '"evidence":{"commands":[]}}'
                        )
                    }
                }
            ]
        }
    )
    assert result.changes[0].path == "backend/app.py"
    assert result.self_review["result"] == "reviewed"

    normalized = parse_execution_result(
        {
            "changes": [{"path": "backend/app.py", "action": "modify", "diff": "@@"}],
            "self_review": "Reviewed against the supplied repository context.",
        }
    )
    assert normalized.self_review == {
        "result": "Reviewed against the supplied repository context."
    }

    normalized_evidence = parse_execution_result(
        {
            "changes": [{"path": "backend/app.py", "action": "modify", "diff": "@@"}],
            "self_review": {"result": "reviewed"},
            "evidence": ["provider did not structure this metadata"],
        }
    )
    assert normalized_evidence.evidence["provider_evidence"] == [
        "provider did not structure this metadata"
    ]

    with pytest.raises(AgentExecutionError):
        parse_execution_result({"output": '{"changes": [], "self_review": {"result": "nope"}}'})

    with pytest.raises(AgentExecutionError):
        parse_execution_result(
            {
                "changes": [{"path": "../escape", "action": "modify", "diff": "@@"}],
                "self_review": {"result": "reviewed"},
            }
        )


def test_implementation_provider_selection_supports_heroku_runpod_fallback():
    executor = ManagedInferenceAgentExecutor(
        {
            "AGENT_IMPLEMENTATION_PROVIDER": "heroku,runpod",
            "AGENT_IMPLEMENTATION_TIMEOUT_SECONDS": 5,
            "HEROKU_INFERENCE_BASE_URL": "https://us.inference.heroku.com",
            "HEROKU_INFERENCE_KEY": "heroku-test-key",
            "HEROKU_INFERENCE_MODEL": "test-model",
            "RUNPOD_API_KEY": "runpod-test-key",
            "RUNPOD_ENDPOINT_ID": "endpoint-test",
            "RUNPOD_INFERENCE_URL": "https://runpod.test/runsync",
        }
    )
    assert executor.provider == "heroku+runpod"
    assert executor._endpoint("heroku")[0].endswith("/v1/chat/completions")
    assert executor._endpoint("runpod")[0] == "https://runpod.test/runsync"


def test_disabled_implementation_provider_fails_closed():
    with pytest.raises(AgentExecutionError):
        ManagedInferenceAgentExecutor({"AGENT_IMPLEMENTATION_PROVIDER": "disabled"})


def test_managed_executor_preserves_provider_usage_and_cost(monkeypatch):
    executor = ManagedInferenceAgentExecutor(
        {
            "AGENT_IMPLEMENTATION_PROVIDER": "heroku",
            "HEROKU_INFERENCE_BASE_URL": "https://inference.example",
            "HEROKU_INFERENCE_KEY": "test-key",
            "HEROKU_INFERENCE_MODEL": "test-model",
        }
    )
    monkeypatch.setattr(
        executor,
        "_request",
        lambda provider, prompt: {
            "choices": [
                {
                    "message": {
                        "content": '{"changes":[{"path":"tests/test_EXAMPLE.py","action":"add","diff":"@@"}],"self_review":{"result":"reviewed"}}'
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "cost": 0.0125,
        },
    )
    run = SimpleNamespace(
        objective="test usage capture",
        environment={"branch": "agent/test", "base_commit": "base"},
        writable_paths=["tests"],
        allowed_tools=["read", "write"],
        model_config={},
    )
    result = executor.execute(run, {"steps": []})
    assert result.evidence["provider_usage"]["total_tokens"] == 15
    assert result.evidence["provider_cost"] == 0.0125


def test_managed_inference_endpoints_must_use_https():
    executor = ManagedInferenceAgentExecutor(
        {
            "AGENT_IMPLEMENTATION_PROVIDER": "heroku",
            "HEROKU_INFERENCE_BASE_URL": "http://insecure.example",
            "HEROKU_INFERENCE_KEY": "test-key",
            "HEROKU_INFERENCE_MODEL": "test-model",
        }
    )
    with pytest.raises(AgentExecutionError, match="HTTPS"):
        executor._endpoint("heroku")

    with pytest.raises(ValidationError, match="HTTPS"):
        configured_analyzer(
            {
                "REQUIREMENT_ANALYSIS_PROVIDER": "runpod",
                "RUNPOD_API_KEY": "test-key",
                "RUNPOD_ENDPOINT_ID": "test-endpoint",
                "RUNPOD_INFERENCE_URL": "http://insecure.example",
            }
        )


def test_snapshot_diff_validation_rejects_invented_context():
    snapshot = (
        "Approved repository snapshot (tests/test_auth.py, exact current content):\n"
        "first\nsecond\nthird\n\nRequested single-file change: test"
    )
    validate_diff_against_snapshot(
        "--- tests/test_auth.py\n+++ tests/test_auth.py\n@@ -2,1 +2,2 @@\n second\n+added",
        "tests/test_auth.py",
        snapshot,
    )
    with pytest.raises(AgentExecutionError, match="does not apply"):
        validate_diff_against_snapshot(
            "--- tests/test_auth.py\n+++ tests/test_auth.py\n@@ -2,1 +2,2 @@\n stale\n+added",
            "tests/test_auth.py",
            snapshot,
        )


def test_checkpoint_recovery_context_is_preserved_for_provider_execution():
    run = SimpleNamespace(
        objective="resume safely",
        environment={"branch": "agent/resume", "base_commit": "abc"},
        writable_paths=["tests"],
        allowed_tools=["read"],
    )
    prompt = _implementation_prompt(run, {"steps": []}, {"sequence": 3, "step": "verify"})
    assert '"resume_checkpoint": {"sequence": 3, "step": "verify"}' in prompt


class EXAMPLEExecutor:
    seen_checkpoints: list[dict | None] = []

    def execute(self, run, plan, checkpoint=None):
        self.seen_checkpoints.append(checkpoint)
        return ExecutionResult(
            provider="EXAMPLE-fixture",
            changes=[
                GeneratedChange(
                    path="backend/EXAMPLE.py",
                    action="add",
                    diff="--- /dev/null\n+++ b/backend/EXAMPLE.py\n@@\n+def EXAMPLE():\n+    return True\n",
                )
            ],
            self_review={"result": "Reviewed against the approved EXAMPLE plan."},
            evidence={"commands": [], "fixture": True},
        )


def test_leased_worker_persists_only_a_reviewable_draft_change_set(app, client, auth_headers, org):
    from app.extensions import db
    from app.models import AgentCheckpoint, AgentRun, ChangeSet
    from app.utils import new_uuid, utcnow

    reviewer_user = LocalProvider(org.slug).ensure_local_user(
        "worker-reviewer@test.local", "password123", "Worker Reviewer", ["product_owner"]
    )
    reviewer = {
        "Authorization": "Bearer "
        + client.post(
            "/api/v1/auth/login",
            json={
                "email": reviewer_user.email,
                "password": "password123",
                "organization": org.slug,
            },
        ).get_json()["data"]["token"]
    }
    admin = auth_headers()
    project = client.post(
        "/api/v1/projects", headers=admin, json={"name": "Worker EXAMPLE", "key": "wEXAMPLE"}
    ).get_json()["data"]
    baseline = client.post(
        "/api/v1/requirements/baselines",
        headers=admin,
        json={
            "project_id": project["id"],
            "title": "Worker Intake",
            "content": {
                "goals": ["Deliver a reviewable change"],
                "functional_specifications": ["The EXAMPLE function returns true"],
                "constraints": [],
                "acceptance_expectations": ["The EXAMPLE function returns true"],
                "attachments": [],
                "repository_references": [],
            },
        },
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
            "project_id": project["id"],
            "source_baseline_id": baseline["id"],
            "title": "Worker Architecture",
            "content": {
                "context": {"goal": "reviewable change"},
                "components": ["api"],
                "data": ["postgres"],
                "integrations": ["git"],
                "deployment": ["docker"],
                "security": ["audit"],
                "operations": ["worker"],
                "threats": ["provider output"],
                "failures": ["provider outage"],
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
    plan = client.post(
        "/api/v1/plans",
        headers=admin,
        json={
            "project_id": project["id"],
            "source_architecture_id": architecture["id"],
            "title": "Worker Plan",
            "content": {
                "steps": [{"id": "EXAMPLE", "title": "Implement", "validation": "pytest"}],
                "environment_manifest": {},
                "budget": {"max_minutes": 10, "max_cost": 1},
                "permissions": {"tools": ["read"], "paths": ["backend"]},
                "escalation_rules": ["pause on failure"],
                "feasibility": {"toolchain": "available"},
            },
        },
    ).get_json()["data"]
    client.post(f"/api/v1/plans/{plan['id']}/submit", headers=admin)
    assert client.post(f"/api/v1/plans/{plan['id']}/approve", headers=reviewer).status_code == 200
    run = client.post(
        "/api/v1/agent-runs",
        headers=admin,
        json={
            "plan_id": plan["id"],
            "objective": "Implement the EXAMPLE function",
            "allowed_tools": ["read"],
            "writable_paths": ["backend"],
            "environment": {"branch": "agent/EXAMPLE", "base_commit": "abc123"},
        },
    ).get_json()["data"]
    client.post(f"/api/v1/agent-runs/{run['id']}/start", headers=admin)
    with app.app_context():
        run_model = AgentRun.query.filter_by(id=uuid.UUID(run["id"])).one()
        db.session.add(
            AgentCheckpoint(
                id=new_uuid(),
                organization_id=run_model.organization_id,
                run_id=run_model.id,
                sequence=1,
                state={"sequence": 1, "step": "provider-request-created"},
                evidence={"source": "checkpoint-recovery-test"},
            )
        )
        db.session.commit()

    interrupted = AgentRunWorker(app, worker_id="interrupted-worker")
    with app.app_context():
        claimed = interrupted._claim()
        assert claimed is not None
        assert claimed.worker_id == "interrupted-worker"
        claimed.lease_expires_at = utcnow() - timedelta(seconds=1)
        db.session.commit()

    EXAMPLEExecutor.seen_checkpoints = []
    app.config["AGENT_RUN_EXECUTOR_FACTORY"] = lambda _app, _run: EXAMPLEExecutor()

    assert AgentRunWorker(app, worker_id="recovery-worker").process_once() is True
    change_set = ChangeSet.query.filter_by(run_id=uuid.UUID(run["id"])).one()
    assert change_set.status == "draft"
    assert change_set.branch == "agent/EXAMPLE"
    assert [item.path for item in change_set.files] == ["backend/EXAMPLE.py"]
    assert change_set.self_review["result"]
    assert EXAMPLEExecutor.seen_checkpoints == [
        {"sequence": 1, "step": "provider-request-created"}
    ]
