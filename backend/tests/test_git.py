import pytest

from app.extensions import db
from app.git.adapter import GitAdapter
from app.git.backend import CommandResult as GitCommandResult
from app.git.backend import FakeGitBackend
from app.git.keys import KnownHosts, normalize_host, parse_ssh_url
from app.models import Project


def _adapter(tmp_path, backend=None):
    key_dir = str(tmp_path / "keys")
    known = str(tmp_path / "known_hosts")
    return GitAdapter("ssh", key_dir, known, backend=backend or FakeGitBackend())


@pytest.fixture()
def project(org):
    p = Project(name="Pilot", key="pil", organization_id=org.id)
    db.session.add(p)
    db.session.commit()
    return p


def test_parse_ssh_urls():
    from app.errors import ValidationError

    assert parse_ssh_url("git@github.com:org/repo.git") == ("github.com", 22)
    assert parse_ssh_url("ssh://git@github.com:2222/org/repo.git") == ("github.com", 2222)
    with pytest.raises(ValidationError):
        parse_ssh_url("https://github.com/org/repo.git")


def test_normalize_host():
    assert normalize_host("github.com") == "github.com"
    assert normalize_host("ssh://git@gitlab.com") == "gitlab.com"


def test_known_hosts_roundtrip(tmp_path):
    kh = KnownHosts(str(tmp_path / "known_hosts"))
    line = "github.com ssh-ed25519 AAAAC3NzaC1234567890"
    kh.add("github.com", line)
    assert kh.contains("github.com")
    assert kh.read_entries()["github.com"] == line
    kh.remove("github.com")
    assert not kh.contains("github.com")


def test_provision_and_connect(project, tmp_path):
    adapter = _adapter(tmp_path)
    repo = adapter.create_repository_record(project, "git@github.com:org/repo.git", "rw", "main")
    assert repo.status == "pending"
    public = adapter.provision_key(repo)
    assert "ssh-ed25519" in public or "AAAAC3" in public
    assert repo.status == "key_ready"
    calls = [c[0] for c in adapter.backend.calls]
    assert "generate_keypair" in calls
    assert "scan_host_key" in calls

    adapter.test_connection(repo)
    assert repo.status == "active"


def test_rotate_and_revoke(project, tmp_path):
    adapter = _adapter(tmp_path)
    repo = adapter.create_repository_record(project, "git@github.com:org/repo.git", "ro", "main")
    adapter.provision_key(repo)
    adapter.rotate_key(repo)
    key_calls = sum(1 for c in adapter.backend.calls if c[0] == "generate_keypair")
    assert key_calls == 2
    adapter.revoke(repo)
    assert repo.status == "revoked"
    assert repo.deploy_key_public is None


def test_clone_and_sync(project, tmp_path):
    adapter = _adapter(tmp_path)
    workspace = str(tmp_path / "ws")
    repo = adapter.create_repository_record(project, "git@example.com:acme/app.git", "rw", "main")
    adapter.provision_key(repo)
    adapter.clone(repo, workspace)
    assert (tmp_path / "ws").exists()
    head = adapter.sync(repo, workspace)
    assert head.startswith("c0ffee000")


def test_connection_failure_marks_failed(project, tmp_path):
    from app.errors import ConflictError

    backend = FakeGitBackend()
    backend.results["ls_remote"] = GitCommandResult(
        False, "", "Host key verification failed.", "ls"
    )
    adapter = _adapter(tmp_path, backend)
    repo = adapter.create_repository_record(project, "git@unknown-host:org/repo.git", "rw", "main")
    adapter.provision_key(repo)
    with pytest.raises(ConflictError):
        adapter.test_connection(repo)
    assert repo.status == "failed"


def test_repo_requires_scope(client, auth_headers, org):
    project = client.post(
        "/api/v1/projects",
        headers=auth_headers(),
        json={"name": "X", "key": "px", "default_branch": "main"},
    ).get_json()["data"]
    get = client.get(f"/api/v1/projects/{project['id']}/repository", headers=auth_headers())
    assert get.status_code == 200
    assert get.get_json().get("data") is None
    post = client.post(
        f"/api/v1/projects/{project['id']}/repository",
        headers=auth_headers(),
        json={"ssh_url": "git@github.com:org/repo.git", "scope": "rw", "default_branch": "main"},
    )
    assert post.status_code == 201
    repo = post.get_json()["data"]
    assert repo["host"] == "github.com"


def test_repo_write_requires_repository_write_scope(client, auth_headers, login, org):
    from app.auth.providers.local import LocalProvider

    project = client.post(
        "/api/v1/projects",
        headers=auth_headers(),
        json={"name": "Scoped", "key": "scoped", "default_branch": "main"},
    ).get_json()["data"]
    LocalProvider(org.slug).ensure_local_user(
        "architect@test.local", "password123", "Architect", ["architect"]
    )
    architect_token = login(email="architect@test.local")
    headers = {"Authorization": f"Bearer {architect_token}"}
    response = client.post(
        f"/api/v1/projects/{project['id']}/repository",
        headers=headers,
        json={"ssh_url": "git@github.com:org/repo.git"},
    )
    assert response.status_code in (401, 403)


def _ok_run(seen=None):
    def run(args, cwd=None, env=None, **kwargs):
        if seen is not None:
            seen["args"] = args
            seen["env"] = env
        return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    return run


def test_command_backend_forwards_ssh_env(monkeypatch):
    from app.git.backend import GitCommandBackend

    seen: dict = {}
    monkeypatch.setattr("app.git.backend.subprocess.run", _ok_run(seen))
    result = GitCommandBackend().clone("git@host:repo.git", "/tmp/dest", "/tmp/key", "/tmp/kh")
    assert result.ok
    assert seen["args"][:3] == ["git", "clone", "--recursive"]
    assert "GIT_SSH_COMMAND" in seen["env"]
    assert "-i /tmp/key" in seen["env"]["GIT_SSH_COMMAND"]
    assert "StrictHostKeyChecking=yes" in seen["env"]["GIT_SSH_COMMAND"]


def test_generate_keypair_removes_existing_before_keygen(monkeypatch, tmp_path):
    from app.git.backend import GitCommandBackend

    key = tmp_path / "k"
    key.write_text("old-priv")
    (tmp_path / "k.pub").write_text("old-pub")
    seen: dict = {}

    def run(args, cwd=None, env=None, **kwargs):
        seen["priv_exists"] = key.exists()
        seen["pub_exists"] = (tmp_path / "k.pub").exists()
        return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("app.git.backend.subprocess.run", run)
    GitCommandBackend().generate_keypair(str(key))
    assert seen["priv_exists"] is False
    assert seen["pub_exists"] is False


def test_sync_resets_to_remote(project, tmp_path):
    backend = FakeGitBackend()
    adapter = _adapter(tmp_path, backend)
    workspace = str(tmp_path / "ws")
    repo = adapter.create_repository_record(project, "git@example.com:acme/app.git", "rw", "main")
    adapter.provision_key(repo)
    adapter.sync(repo, workspace)
    resets = [c for c in backend.calls if c[0] == "reset_hard"]
    assert resets, "sync must fast-forward the local branch to the remote"
    assert resets[-1][1] == workspace
    assert resets[-1][2] == "origin/main"
