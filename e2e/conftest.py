import os
import time
import uuid

import pytest
import requests


class ApiClient:
    def __init__(self, base_url: str, token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def request(self, method: str, path: str, *, expected=None, **kwargs):
        response = self.session.request(
            method,
            f"{self.base_url}{path}",
            timeout=float(os.environ.get("BOTQ_E2E_REQUEST_TIMEOUT", "30")),
            **kwargs,
        )
        if expected is not None:
            expected_statuses = (
                {expected} if isinstance(expected, int) else set(expected)
            )
            if response.status_code not in expected_statuses:
                pytest.fail(
                    f"{method} {path} returned {response.status_code}, "
                    f"expected {sorted(expected_statuses)}: {response.text[:1000]}"
                )
        return response

    def data(self, method: str, path: str, *, expected=(200, 201), **kwargs):
        response = self.request(method, path, expected=expected, **kwargs)
        body = response.json()
        assert body.get("error") is None, body
        return body["data"]


def _login(base_url: str, email: str, password: str, organization: str) -> ApiClient:
    client = ApiClient(base_url)
    response = client.request(
        "POST",
        "/api/v1/auth/login",
        json={"email": email, "password": password, "organization": organization},
        expected=200,
    )
    payload = response.json()["data"]
    assert payload["user"]["email"] == email
    return ApiClient(base_url, payload["token"])


@pytest.fixture(scope="session")
def e2e_base_url():
    return os.environ.get("BOTQ_E2E_BASE_URL", "http://127.0.0.1:8885").rstrip("/")


@pytest.fixture(scope="session", autouse=True)
def e2e_ready(e2e_base_url):
    deadline = time.monotonic() + int(os.environ.get("BOTQ_E2E_READY_TIMEOUT", "90"))
    last_error = "service did not respond"
    while time.monotonic() < deadline:
        try:
            response = requests.get(f"{e2e_base_url}/health/ready", timeout=5)
            if (
                response.status_code == 200
                and response.json().get("data", {}).get("status") == "ready"
            ):
                return
            last_error = f"HTTP {response.status_code}: {response.text[:300]}"
        except requests.RequestException as exc:
            last_error = str(exc)
        time.sleep(2)
    pytest.fail(
        f"E2E target is not ready: {last_error}. "
        "Start it with scripts/run_e2e.ps1 before invoking pytest."
    )


@pytest.fixture(scope="session")
def admin(e2e_base_url, e2e_ready):
    return _login(
        e2e_base_url,
        os.environ.get("BOTQ_E2E_ADMIN_EMAIL", "admin@acme.local"),
        os.environ.get("BOTQ_E2E_PASSWORD", "E2ePass!2026"),
        os.environ.get("BOTQ_E2E_ORG", "acme"),
    )


@pytest.fixture(scope="session")
def reviewer(e2e_base_url, e2e_ready):
    return _login(
        e2e_base_url,
        os.environ.get("BOTQ_E2E_REVIEWER_EMAIL", "reviewer@acme.local"),
        os.environ.get("BOTQ_E2E_PASSWORD", "E2ePass!2026"),
        os.environ.get("BOTQ_E2E_ORG", "acme"),
    )


@pytest.fixture(scope="session")
def unique_suffix():
    return uuid.uuid4().hex[:10]
