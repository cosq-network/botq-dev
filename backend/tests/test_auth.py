from app.auth.tokens import create_token, is_valid, revoke_token
from app.models import Token


def test_local_login_success(client, org, admin):
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.local", "password": "password123", "organization": org.slug},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"]["token"]
    assert body["data"]["user"]["email"] == "admin@test.local"
    assert "organization_administrator" in body["data"]["user"]["roles"]


def test_local_login_failure(client, org):
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.local", "password": "wrong", "organization": org.slug},
    )
    assert resp.status_code == 401


def test_session_flow(client, org, auth_headers):
    headers = auth_headers()
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    scopes = me.get_json()["data"]["scopes"]
    assert "admin" in scopes

    logout = client.post("/api/v1/auth/logout", headers=headers)
    assert logout.status_code == 200

    me2 = client.get("/api/v1/auth/me", headers=headers)
    assert me2.status_code == 401


def test_scope_enforced(client, org, developer, login):
    dev_token = login(email="dev@test.local")
    dev_headers = {"Authorization": f"Bearer {dev_token}"}

    assert client.get("/api/v1/audit/events", headers=dev_headers).status_code == 403
    assert client.get("/api/v1/secrets", headers=dev_headers).status_code in (401, 403)


def test_providers_endpoint(client):
    resp = client.get("/api/v1/auth/providers")
    assert resp.status_code == 200
    names = [p["name"] for p in resp.get_json()["data"]]
    assert "local" in names


def test_token_lifecycle(admin):
    raw, token = create_token(admin, 3600)
    assert is_valid(token)
    token_hash = token.token_hash
    revoke_token(token)
    assert not is_valid(token)
    stored = Token.query.get(token.id)
    assert stored.token_hash == token_hash
    assert stored.revoked_at is not None


def test_local_login_is_scoped_to_requested_organization(client, org):
    from app.auth.providers.local import LocalProvider
    from app.orgs.service import create_organization

    other = create_organization("Other Auth Org", slug="other-auth")
    LocalProvider(org.slug).ensure_local_user(
        "same@example.test", "org-one-password", "Org One", ["developer"]
    )
    LocalProvider(other.slug).ensure_local_user(
        "same@example.test", "org-two-password", "Org Two", ["developer"]
    )

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "same@example.test",
            "password": "org-two-password",
            "organization": other.slug,
        },
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["organization"]["slug"] == other.slug

    wrong_org = client.post(
        "/api/v1/auth/login",
        json={
            "email": "same@example.test",
            "password": "org-two-password",
            "organization": org.slug,
        },
    )
    assert wrong_org.status_code == 401
