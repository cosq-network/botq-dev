from app.secrets.manager import decrypt_value, encrypt_value
from app.secrets.masking import contains_secret, mask_value, redact_text
from app.secrets.policy import (
    decide_injection,
    prompt_allowed_by_default,
    secret_blocked_from_prompt,
)


def test_round_trip_encryption():
    value = "sk-prod-abc123"
    enc = encrypt_value(value, app_secret_key="k1", configured_key="")
    assert enc.startswith("fernet:")
    assert value not in enc
    assert decrypt_value(enc, app_secret_key="k1", configured_key="") == value


def test_encryption_differs_across_keys():
    enc1 = encrypt_value("same-password", "k1")
    enc2 = encrypt_value("same-password", "k2")
    assert enc1 != enc2
    assert decrypt_value(enc1, "k1") == "same-password"
    try:
        decrypt_value(enc1, "worse-key")
        raise AssertionError("expected decryption failure with wrong key")
    except Exception:
        pass


def test_configured_fernet_key_wins():
    from cryptography.fernet import Fernet

    configured = Fernet.generate_key().decode()
    enc = encrypt_value("value", "any", configured_key=configured)
    assert decrypt_value(enc, "any", configured_key=configured) == "value"


def test_masking():
    assert mask_value("supersecret") == "su*******et"
    assert mask_value("ab") == "**"
    assert mask_value("") == ""


def test_redact_text_hides_all_values():
    text = "apikey=sk-live-111 call sk-live-111 again"
    out = redact_text(text, ["sk-live-111"])
    assert "sk-live-111" not in out
    assert out.count("***REDACTED***") == 2


def test_contains_secret():
    assert contains_secret(["sk-abc"], "prompt with sk-abc inside")
    assert not contains_secret(["sk-abc"], "no secrets here")


def test_injection_policy():
    assert (
        decide_injection(
            has_inject_scope=True, reputation_ok=True, purpose="repo", job_purpose="repo"
        ).allowed
        is True
    )
    denied = decide_injection(
        has_inject_scope=False, reputation_ok=True, purpose="repo", job_purpose="repo"
    )
    assert denied.allowed is False
    mismatch = decide_injection(
        has_inject_scope=True, reputation_ok=True, purpose="repo", job_purpose="build"
    )
    assert mismatch.allowed is False


def test_prompt_forbidden_by_default():
    assert prompt_allowed_by_default() is False
    assert secret_blocked_from_prompt(["tok_123"], "instructions: use tok_123") is True


def test_secret_api_never_leaks_value(client, auth_headers, app, org):
    resp = client.post(
        "/api/v1/secrets",
        headers=auth_headers(),
        json={"name": "OPENAI_API_KEY", "value": "sk-live-999", "purpose": "inference"},
    )
    assert resp.status_code == 201
    body = resp.get_json()["data"]
    assert "sk-live-999" not in body

    listing = client.get("/api/v1/secrets", headers=auth_headers()).get_json()["data"]
    assert "sk-live-999" not in repr(listing)

    got = client.get(f"/api/v1/secrets/{body['id']}", headers=auth_headers()).get_json()
    assert "sk-live-999" not in repr(got)

    from app.models import Secret

    stored = Secret.query.filter_by(name="OPENAI_API_KEY", organization_id=org.id).one()
    assert "sk-live-999" not in stored.encrypted_value
    assert (
        decrypt_value(
            stored.encrypted_value, app.config["SECRET_KEY"], app.config["SECRET_ENCRYPTION_KEY"]
        )
        == "sk-live-999"
    )


def test_secret_rotate_and_verify(client, auth_headers):
    created = client.post(
        "/api/v1/secrets",
        headers=auth_headers(),
        json={"name": "DB_PASSWORD", "value": "old-password"},
    ).get_json()["data"]
    rotated = client.post(
        f"/api/v1/secrets/{created['id']}/rotate",
        headers=auth_headers(),
        json={"value": "new-password"},
    )
    assert rotated.status_code == 200
    verified = client.post(f"/api/v1/secrets/{created['id']}/verify", headers=auth_headers())
    assert verified.status_code == 200
    assert verified.get_json()["data"]["verified"] is True


def test_secret_access_audited(client, auth_headers, org):
    created = client.post(
        "/api/v1/secrets",
        headers=auth_headers(),
        json={"name": "TOKEN_X", "value": "v"},
    ).get_json()["data"]
    client.get(f"/api/v1/secrets/{created['id']}", headers=auth_headers())
    from app.models import AuditEvent

    actions = [e.action for e in AuditEvent.query.filter_by(organization_id=org.id).all()]
    assert "secret.created" in actions
    assert "secret.accessed" in actions
