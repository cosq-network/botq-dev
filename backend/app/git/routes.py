import pathlib

from flask import Blueprint, current_app, g, request

from ..api.responses import ok
from ..audit.service import record_audit
from ..auth.decorators import require_scope
from ..errors import AuthenticationError, NotFoundError, ValidationError
from ..extensions import db
from ..models import Project, RepositoryConnection
from .adapter import GitAdapter
from .keys import normalize_host

bp = Blueprint("git", __name__, url_prefix="/projects/<uuid:project_id>/repository")


def _adapter() -> GitAdapter:
    factory = current_app.config.get("GIT_ADAPTER_FACTORY")
    if factory is not None:
        return factory()
    return GitAdapter(
        ssh_bin=current_app.config["GIT_SSH"],
        key_dir=current_app.config["GIT_KEY_DIR"],
        known_hosts_path=current_app.config["GIT_KNOWN_HOSTS"],
    )


def _serialize(repo: RepositoryConnection) -> dict:
    return {
        "id": str(repo.id),
        "ssh_url": repo.ssh_url,
        "host": repo.host,
        "host_fingerprint_verified": bool(repo.host_fingerprint),
        "scope": repo.scope,
        "default_branch": repo.default_branch,
        "status": repo.status,
        "deploy_key_public": repo.deploy_key_public,
        "last_sync_at": repo.last_sync_at.isoformat() if repo.last_sync_at else None,
        "last_error": repo.last_error,
    }


@bp.get("")
@require_scope("repository:read")
def get_connection(project_id):
    repo = _repo_or_none(project_id)
    if repo is None:
        return ok(None)
    return ok(_serialize(repo))


@bp.post("")
@require_scope("repository:write")
def connect(project_id):
    project = _get_project(project_id)
    payload = request.get_json(silent=True) or {}
    ssh_url = (payload.get("ssh_url") or "").strip()
    scope = (payload.get("scope") or "rw").strip().lower()
    default_branch = (payload.get("default_branch") or project.default_branch or "main").strip()
    if not ssh_url:
        raise ValidationError("ssh_url is required")
    adapter = _adapter()
    repo = adapter.create_repository_record(project, ssh_url, scope, default_branch)
    try:
        public_key = adapter.provision_key(repo)
        host_key = adapter.known_hosts.fingerprints(repo.host)
        repo.host_fingerprint = (
            host_key[0].split()[2] if host_key and len(host_key[0].split()) > 2 else "verified"
        )
    except Exception as exc:
        repo.status = "key_error"
        repo.last_error = str(exc)
        db.session.commit()
        from ..errors import ConflictError

        raise ConflictError(str(exc), code="key_provision_failed") from None
    record_audit(
        action="repository.connected",
        actor_id=str(g.user.id),
        target_type="repository",
        target_id=repo.id,
        organization_id=_org().id,
        metadata={"host": repo.host, "ssh_url": _masked_url(repo.ssh_url)},
    )
    return ok({**_serialize(repo), "deploy_key_public": public_key}, status=201)


@bp.post("/test")
@require_scope("repository:read")
def test_connection(project_id):
    repo = _get_repo(project_id)
    adapter = _adapter()
    adapter.test_connection(repo)
    record_audit(
        action="repository.tested",
        actor_id=str(g.user.id),
        target_type="repository",
        target_id=repo.id,
        organization_id=_org().id,
        metadata={"host": repo.host, "result": repo.status},
    )
    return ok(_serialize(repo))


@bp.post("/rotate-key")
@require_scope("repository:write")
def rotate_key(project_id):
    repo = _get_repo(project_id)
    adapter = _adapter()
    public_key = adapter.rotate_key(repo)
    record_audit(
        action="repository.key_rotated",
        actor_id=str(g.user.id),
        target_type="repository",
        target_id=repo.id,
        organization_id=_org().id,
        metadata={"host": repo.host},
    )
    return ok({**_serialize(repo), "deploy_key_public": public_key})


@bp.post("/revoke")
@require_scope("repository:write")
def revoke(project_id):
    repo = _get_repo(project_id)
    adapter = _adapter()
    adapter.revoke(repo)
    record_audit(
        action="repository.key_revoked",
        actor_id=str(g.user.id),
        target_type="repository",
        target_id=repo.id,
        organization_id=_org().id,
        metadata={"host": repo.host},
    )
    return ok(_serialize(repo))


@bp.post("/sync")
@require_scope("repository:write")
def sync(project_id):
    repo = _get_repo(project_id)
    adapter = _adapter()
    workspace = pathlib.Path(current_app.config["SANDBOX_WORKSPACE_DIR"]) / str(project_id)
    workspace.mkdir(parents=True, exist_ok=True)
    if not (workspace / ".git").exists():
        adapter.clone(repo, str(workspace))
    head = adapter.sync(repo, str(workspace))
    record_audit(
        action="repository.synced",
        actor_id=str(g.user.id),
        target_type="repository",
        target_id=repo.id,
        organization_id=_org().id,
        metadata={"host": repo.host, "head": head},
    )
    return ok({**_serialize(repo), "head": head, "workspace": str(workspace)})


def _masked_url(ssh_url: str) -> str:
    host = normalize_host(ssh_url)
    return f"ssh://***@{host}/***"


def _org():
    org = getattr(g, "organization", None)
    if org is None:
        raise AuthenticationError("Authenticated organization not found")
    return org


def _get_project(project_id) -> Project:
    project = Project.query.filter_by(id=project_id, organization_id=_org().id).first()
    if project is None:
        raise NotFoundError("Project not found")
    return project


def _repo_or_none(project_id) -> RepositoryConnection | None:
    return RepositoryConnection.query.filter_by(
        project_id=project_id, organization_id=_org().id
    ).first()


def _get_repo(project_id) -> RepositoryConnection:
    repo = _repo_or_none(project_id)
    if repo is None:
        raise NotFoundError("Repository connection not found")
    return repo
