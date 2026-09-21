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
