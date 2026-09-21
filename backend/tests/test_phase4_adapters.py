import pytest

from app import create_app
from app.design.preview import PreviewDeploymentError, parse_provisioned_preview


def test_phase4_workbench_route_is_public_shell():
    app = create_app()
    response = app.test_client().get("/workbench")
    assert response.status_code == 200
    assert b"Phase 4 acceptance workbench" in response.data


def test_preview_deployment_response_requires_https_url():
    provisioned = parse_provisioned_preview(
        {
            "url": "https://preview.example.test/run/123",
            "deployment_id": "deploy-123",
            "evidence": {"provider": "preview-host"},
        }
    )
    assert provisioned.url.startswith("https://")
    assert provisioned.deployment_id == "deploy-123"

    with pytest.raises(PreviewDeploymentError):
        parse_provisioned_preview({"url": "http://preview.example.test/run/123"})


def test_preview_deployment_response_rejects_invalid_evidence():
    with pytest.raises(PreviewDeploymentError):
        parse_provisioned_preview({"url": "https://preview.example.test/run/123", "evidence": []})
