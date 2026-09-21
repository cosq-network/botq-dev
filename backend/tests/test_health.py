import pytest


def test_liveness(client):
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "ok"


def test_readiness_ok(client):
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["database"] == "up"


def test_ping_public(client):
    resp = client.get("/api/v1/ping")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["service"] == "botq"


def test_index_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"AI Software Delivery Platform" in resp.data


def test_protected_endpoint_requires_auth(client):
    resp = client.get("/api/v1/projects")
    assert resp.status_code == 401
    assert resp.get_json()["ok"] is False


def test_production_rejects_host_sandbox_network():
    from cryptography.fernet import Fernet

    from app import create_app
    from app.config import Config

    class ProductionConfig(Config):
        ENVIRONMENT = "production"
        SECRET_KEY = "production-secret"
        AUDIT_SECRET = "production-audit-secret"
        SECRET_ENCRYPTION_KEY = Fernet.generate_key().decode()
        RATE_LIMIT_ENABLED = True
        RATE_LIMIT_BACKEND = "redis"
        REDIS_URL = "redis://production-test.invalid:6379/0"
        BOOTSTRAP_ENABLED = False
        SANDBOX_NETWORK_ALLOWLIST = ["none", "host"]
        SQLALCHEMY_DATABASE_URI = "sqlite://"

    with pytest.raises(RuntimeError, match="Host sandbox networking"):
        create_app(ProductionConfig)
