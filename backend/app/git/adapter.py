import pathlib

from ..errors import ConflictError, ValidationError
from ..models import RepositoryConnection
from ..utils import new_uuid, utcnow
from .backend import GitCommandBackend
from .keys import KnownHosts, deploy_key_paths, normalize_host, parse_ssh_url


class GitAdapter:
    def __init__(self, ssh_bin: str, key_dir: str, known_hosts_path: str, backend=None):
        self.ssh_bin = ssh_bin
        self.key_dir = key_dir
        self.known_hosts = KnownHosts(known_hosts_path)
        self.backend = backend or GitCommandBackend(ssh_bin=ssh_bin)

    def create_repository_record(
        self, project, ssh_url: str, scope: str, default_branch: str
    ) -> RepositoryConnection:
        host, _port = parse_ssh_url(ssh_url)
        if scope not in {"ro", "rw"}:
            raise ValidationError("Repository scope must be 'ro' or 'rw'")
        if RepositoryConnection.query.filter_by(project_id=project.id).first():
            raise ConflictError("Project already has a repository connection")
        repo = RepositoryConnection(
            id=new_uuid(),
            organization_id=project.organization_id,
            project_id=project.id,
            ssh_url=ssh_url.strip(),
            host=normalize_host(host),
            scope=scope,
            default_branch=default_branch or project.default_branch,
            status="pending",
        )
        from ..extensions import db

        db.session.add(repo)
        db.session.commit()
        return repo

    def provision_key(self, repo: RepositoryConnection) -> str:
        key_path, pub_path = deploy_key_paths(self._repo_dir(repo))
        result = self.backend.generate_keypair(str(key_path))
        if not result.ok:
            raise RuntimeError(f"Failed to generate deploy key: {result.error}")
        if not pub_path.exists():
            raise RuntimeError("Public key file was not produced")
        public_key = pub_path.read_text(encoding="utf-8").strip()
        self.known_hosts.add(repo.host, self._scan_host(repo.host))
        from ..extensions import db

        repo.deploy_key_public = public_key
        repo.deploy_key_ref = str(key_path)
        repo.status = "key_ready"
        db.session.commit()
        return public_key

    def rotate_key(self, repo: RepositoryConnection) -> str:
        key_path, _ = deploy_key_paths(self._repo_dir(repo))
        result = self.backend.generate_keypair(str(key_path))
        if not result.ok:
            raise RuntimeError(f"Failed to rotate deploy key: {result.error}")
        return self._reload_public_key(repo)

    def _reload_public_key(self, repo: RepositoryConnection) -> str:
        key_path, pub_path = deploy_key_paths(self._repo_dir(repo))
        if not pub_path.exists():
            raise RuntimeError("Public key file is missing after rotation")
        public_key = pub_path.read_text(encoding="utf-8").strip()
        from ..extensions import db

        repo.deploy_key_public = public_key
        repo.last_rotated_at = utcnow()
        repo.status = "key_ready"
        db.session.commit()
        return public_key

    def test_connection(self, repo: RepositoryConnection) -> None:
        key_path, _ = deploy_key_paths(self._repo_dir(repo))
        if not key_path.exists():
            raise ValidationError("Deploy key has not been provisioned", code="key_not_provisioned")
        result = self.backend.ls_remote(repo.ssh_url, str(key_path), self.known_hosts.path)
        if not result.ok:
            repo.status = "failed"
            repo.last_error = result.error
            self._commit()
            raise ConflictError(result.error, code="connection_test_failed")
        repo.status = "active"
        repo.last_error = None
        self._commit()

    def revoke(self, repo: RepositoryConnection) -> None:
        key_path, pub_path = deploy_key_paths(self._repo_dir(repo))
        for p in (key_path, pub_path):
            if p.exists():
                p.unlink()
        from ..extensions import db

        repo.deploy_key_public = None
        repo.deploy_key_ref = None
        repo.status = "revoked"
        db.session.commit()

    def clone(self, repo: RepositoryConnection, destination: str) -> None:
        key_path, _ = deploy_key_paths(self._repo_dir(repo))
        if not key_path.exists():
            raise ValidationError("Deploy key has not been provisioned", code="key_not_provisioned")
        result = self.backend.clone(repo.ssh_url, destination, str(key_path), self.known_hosts.path)
        if not result.ok:
            raise ConflictError(result.error, code="clone_failed")
        second = self.backend.checkout(destination, repo.default_branch)
        if not second.ok:
            result = self.backend.checkout(destination, "main")
            if not result.ok:
                raise ConflictError(result.error, code="checkout_failed")
        from ..extensions import db

        repo.last_sync_at = utcnow()
        db.session.commit()

    def sync(self, repo: RepositoryConnection, destination: str) -> str:
        key_path, _ = deploy_key_paths(self._repo_dir(repo))
        fetch = self.backend.fetch(destination, str(key_path), self.known_hosts.path)
        if not fetch.ok:
            raise ConflictError(fetch.error, code="fetch_failed")
        checkout = self.backend.checkout(destination, repo.default_branch)
        if not checkout.ok:
            raise ConflictError(checkout.error, code="checkout_failed")
        reset = self.backend.reset_hard(destination, f"origin/{repo.default_branch}")
        if not reset.ok:
            raise ConflictError(reset.error, code="reset_failed")
        head = self.backend.current_head(destination)
        from ..extensions import db

        repo.last_sync_at = utcnow()
        db.session.commit()
        return head

    def _scan_host(self, host: str) -> str:
        result = self.backend.scan_host_key(host)
        if not result.ok:
            raise ConflictError(result.error, code="host_key_scan_failed")
        return result.stdout

    def _repo_dir(self, repo: RepositoryConnection) -> str:
        return str(pathlib.Path(self.key_dir) / str(repo.project_id))

    def _commit(self):
        from ..extensions import db

        db.session.commit()
