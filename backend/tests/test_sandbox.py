import pytest

from app.sandbox.readiness import REQUIRED_TOOLS, build_readiness_report
from app.sandbox.runner import DockerSandboxRunner, SandboxDenied, SandboxUnavailable


def test_build_report_structure(monkeypatch):
    monkeypatch.setattr("app.sandbox.readiness.shutil.which", lambda tool: f"/usr/bin/{tool}")
    monkeypatch.setattr(
        "app.sandbox.readiness.subprocess.run",
        lambda *a, **k: type("P", (), {"returncode": 0, "stdout": "1.0\n", "stderr": ""})(),
    )
    monkeypatch.setattr(
        "app.sandbox.readiness.check_docker",
        lambda: {"available": True, "ok": True, "detail": "27"},
    )
    monkeypatch.setattr(
        "app.sandbox.readiness.check_disk", lambda path=".": {"ok": True, "free_gb": 12}
    )
    monkeypatch.setattr(
        "app.sandbox.readiness.check_network",
        lambda targets, timeout=8: {"ok": True, "targets": {}},
    )
    report = build_readiness_report()
    assert report["mandatory_ok"] is True
    for tool in REQUIRED_TOOLS:
        assert tool in report["tools"]
        assert report["tools"][tool]["found"] is True
    assert report["missing_mandatory"] == []
    assert "generated_at" in report


def test_missing_mandatory_tool_fails(monkeypatch):
    def fake_which(tool):
        if tool == "clang":
            return None
        return f"/usr/bin/{tool}"

    monkeypatch.setattr("app.sandbox.readiness.shutil.which", fake_which)
    monkeypatch.setattr(
        "app.sandbox.readiness.subprocess.run",
        lambda *a, **k: type("P", (), {"returncode": 0, "stdout": "1.0\n", "stderr": ""})(),
    )
    monkeypatch.setattr("app.sandbox.readiness.check_docker", lambda: {"ok": True})
    monkeypatch.setattr(
        "app.sandbox.readiness.check_disk", lambda path=".": {"ok": True, "free_gb": 12}
    )
    monkeypatch.setattr(
        "app.sandbox.readiness.check_network",
        lambda targets, timeout=8: {"ok": True, "targets": {}},
    )
    report = build_readiness_report()
    assert report["mandatory_ok"] is False
    assert "clang" in report["missing_mandatory"]


def test_readiness_endpoint(client, auth_headers, monkeypatch, app):
    monkeypatch.setattr("app.sandbox.routes.build_readiness_report", lambda: {"mandatory_ok": True})
    resp = client.get("/api/v1/sandbox/readiness", headers=auth_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"]["mandatory_ok"] is True


def test_runner_rejects_non_allowlisted_image(app):
    runner = DockerSandboxRunner(app)
    with pytest.raises(SandboxDenied):
        runner.run("ubuntu:latest", "true")


def test_runner_rejects_disallowed_network(app):
    runner = DockerSandboxRunner(app)
    with pytest.raises(SandboxDenied):
        runner.run("python:3.13-slim", "true", network="bridge")


def test_runner_unavailable_when_no_sdk(monkeypatch, app):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "docker":
            raise ImportError("no docker")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    runner = DockerSandboxRunner(app)
    with pytest.raises(SandboxUnavailable):
        runner.run("python:3.13-slim", "true")


def test_diagnostic_run_requires_run_scope(client, org, developer, auth_headers):
    assert client.get("/api/v1/sandbox/readiness").status_code == 401


def test_run_probe_ok(monkeypatch):
    from app.sandbox import readiness

    monkeypatch.setattr(
        readiness.subprocess,
        "run",
        lambda *a, **k: type("P", (), {"returncode": 0, "stdout": "ok\n", "stderr": ""})(),
    )
    assert readiness.run_probe_command("echo hi")["ok"] is True
