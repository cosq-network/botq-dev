"""Deterministic HTTP integration tests for configured provider boundaries."""

import json

from app.design.adapter import PenpotAdapter
from app.release.adapter import WebhookDeploymentAdapter
from app.requirements.analysis import HerokuInferenceAnalyzer


def test_penpot_retrieve_uses_bearer_auth_and_redacts_provider_secrets(requests_mock):
    url = "https://penpot.example/api/files/file-1"
    requests_mock.get(url, json={"id": "file-1", "name": "Mockup", "secret": "must-not-leak"})

    result = PenpotAdapter(
        {
            "PENPOT_API_BASE_URL": "https://penpot.example",
            "PENPOT_API_TOKEN": "penpot-test-token",
        }
    ).retrieve("file-1")

    assert result == {"available": True, "data": {"id": "file-1", "name": "Mockup"}}
    request = requests_mock.last_request
    assert request.headers["Authorization"] == "Bearer penpot-test-token"


def test_deployment_webhook_covers_deploy_and_rollback_contract(requests_mock):
    url = "https://deploy.example/webhook"
    requests_mock.post(
        url,
        [{"json": {"status": "healthy", "deployment_id": "deploy-1", "diagnostics": {}, "health_checks": {"ready": True}}},
         {"json": {"status": "rolled_back", "deployment_id": "deploy-1", "diagnostics": {}, "health_checks": {"ready": True}}}],
    )
    adapter = WebhookDeploymentAdapter({"DEPLOYMENT_URL": url, "DEPLOYMENT_TOKEN": "deploy-test-token"})

    deployed = adapter.provision({"deployment_id": "deploy-1", "release": "1.0.0"})
    rolled_back = adapter.rollback({"deployment_id": "deploy-1", "release": "1.0.0"})

    assert deployed.status == "healthy"
    assert rolled_back.status == "rolled_back"
    assert requests_mock.call_count == 2
    assert requests_mock.request_history[0].headers["Authorization"] == "Bearer deploy-test-token"
    assert json.loads(requests_mock.request_history[0].text)["action"] == "deploy"
    assert json.loads(requests_mock.request_history[1].text)["action"] == "rollback"


def test_managed_analysis_provider_sends_schema_constrained_json_request(requests_mock):
    url = "https://inference.example/v1/chat/completions"
    requests_mock.post(url, json={"findings": [], "proposed_work_items": []})
    analyzer = HerokuInferenceAnalyzer(
        base_url="https://inference.example",
        api_key="inference-test-token",
        model="test-model",
        timeout=5,
    )

    result = analyzer.analyze({"functional_specifications": ["The system must authenticate users."]})

    assert result.findings == []
    assert result.proposed_work_items == []
    request = requests_mock.last_request
    assert request.headers["Authorization"] == "Bearer inference-test-token"
    body = json.loads(request.text)
    assert body["response_format"] == {"type": "json_object"}
    assert "The system must authenticate users." in body["messages"][1]["content"]
