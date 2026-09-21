import pytest

from app.release.adapter import (
    DeploymentProviderError,
    LocalComposeDeploymentAdapter,
    WebhookDeploymentAdapter,
    parse_deployment_result,
)


def test_deployment_provider_response_requires_health_contract():
    result = parse_deployment_result(
        {
            "status": "healthy",
            "deployment_id": "deploy-1",
            "diagnostics": {"image": "registry.example/app@sha256:abc"},
            "health_checks": {"ready": True},
        }
    )
    assert result.status == "healthy"
    assert result.provider_id == "deploy-1"

    with pytest.raises(DeploymentProviderError):
        parse_deployment_result({"status": "healthy", "diagnostics": []})


def test_deployment_webhook_requires_https_and_credentials():
    with pytest.raises(DeploymentProviderError, match="DEPLOYMENT_URL"):
        WebhookDeploymentAdapter({})
    with pytest.raises(DeploymentProviderError, match="HTTPS"):
        WebhookDeploymentAdapter(
            {
                "DEPLOYMENT_URL": "http://deploy.example",
                "DEPLOYMENT_TOKEN": "test-token",
            }
        )


def test_local_compose_adapter_accepts_pilot_compose_stack():
    adapter = LocalComposeDeploymentAdapter(
        {
            "LOCAL_COMPOSE_FILE": "docker-compose.yml,docker-compose.pilot.yml",
            "LOCAL_COMPOSE_PROJECT": "botq-pilot-test",
            "LOCAL_DEPLOYMENT_HEALTH_URL": "http://127.0.0.1:18086/health/ready",
            "LOCAL_DEPLOYMENT_HEALTH_TIMEOUT_SECONDS": "5",
        }
    )

    assert adapter.compose_files == ["docker-compose.yml", "docker-compose.pilot.yml"]
    assert adapter.project == "botq-pilot-test"
    assert adapter.health_timeout == 5


def test_local_compose_adapter_rejects_invalid_health_url():
    with pytest.raises(DeploymentProviderError, match="HTTP"):
        LocalComposeDeploymentAdapter(
            {
                "LOCAL_COMPOSE_FILE": "docker-compose.yml",
                "LOCAL_DEPLOYMENT_HEALTH_URL": "/health/ready",
            }
        )


def test_local_compose_rollback_requires_previous_definition():
    adapter = LocalComposeDeploymentAdapter(
        {
            "LOCAL_COMPOSE_FILE": "docker-compose.yml",
            "LOCAL_DEPLOYMENT_HEALTH_URL": "http://127.0.0.1:18086/health/ready",
        }
    )
    with pytest.raises(DeploymentProviderError, match="previous compose definition"):
        adapter.rollback({"deployment_id": "deploy-1", "rollback": {}})


def test_local_compose_rollback_deploys_previous_definition(monkeypatch):
    adapter = LocalComposeDeploymentAdapter(
        {
            "LOCAL_COMPOSE_FILE": "current.yml",
            "LOCAL_DEPLOYMENT_HEALTH_URL": "http://127.0.0.1:18086/health/ready",
        }
    )
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)

        class Completed:
            stdout = "rollback ok"

        return Completed()

    monkeypatch.setattr("app.release.adapter.subprocess.run", fake_run)
    monkeypatch.setattr(adapter, "_wait_for_health", lambda: (True, 200))
    result = adapter.rollback(
        {
            "deployment_id": "deploy-1",
            "rollback": {"compose_files": ["previous.yml"]},
        }
    )
    assert result.status == "healthy"
    assert calls == [["docker", "compose", "-f", "previous.yml", "up", "-d"]]
