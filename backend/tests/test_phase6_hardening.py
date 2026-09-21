def test_metrics_registry_exposes_prometheus_without_sensitive_labels():
    from app.observability import MetricsRegistry

    registry = MetricsRegistry()
    registry.increment("http_requests_total", labels={"method": "GET", "route": "/health/live"})
    registry.set_gauge("health_ready", 1)
    registry.observe("http_request_duration_ms", 12.5, labels={"route": "/health/live"})

    output = registry.prometheus()

    assert 'http_requests_total{method="GET",route="/health/live"} 1' in output
    assert "health_ready 1" in output
    assert "12.5" in output


def test_health_metrics_and_security_headers_are_available(client):
    response = client.get("/health/live", headers={"X-Correlation-ID": "phase6-test"})

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "phase6-test"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "object-src 'none'" in response.headers["Content-Security-Policy"]

    metrics_response = client.get("/health/metrics")
    assert metrics_response.status_code == 200
    assert metrics_response.get_json()["data"]["counters"]
    prometheus = client.get("/health/metrics/prometheus")
    assert prometheus.status_code == 200
    assert "http_requests_total" in prometheus.get_data(as_text=True)


def test_diagnostic_bundle_is_scoped_and_redacted(client, org, developer):
    token_response = client.post(
        "/api/v1/auth/login",
        json={"email": developer.email, "password": "password123", "organization": org.slug},
    )
    headers = {"Authorization": f"Bearer {token_response.get_json()['data']['token']}"}
    response = client.get("/api/v1/diagnostics/bundle", headers=headers)

    assert response.status_code == 403


def test_diagnostic_bundle_and_retention_plan_for_auditor(client, org):
    from app.auth.providers.local import LocalProvider

    LocalProvider(org.slug).ensure_local_user(
        "auditor@test.local", "password123", "Auditor User", ["auditor"]
    )
    token_response = client.post(
        "/api/v1/auth/login",
        json={"email": "auditor@test.local", "password": "password123", "organization": org.slug},
    )
    headers = {"Authorization": f"Bearer {token_response.get_json()['data']['token']}"}

    bundle = client.get("/api/v1/diagnostics/bundle", headers=headers)
    retention = client.get("/api/v1/diagnostics/retention-plan", headers=headers)

    assert bundle.status_code == 200
    assert bundle.get_json()["data"]["redaction"]["excluded"]
    assert retention.status_code == 200
    assert retention.get_json()["data"]["mode"] == "plan_only"
