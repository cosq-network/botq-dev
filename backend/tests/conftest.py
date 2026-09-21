import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("AUDIT_SECRET", "test-audit-chain-secret")
os.environ.setdefault("BOOTSTRAP_TOKEN", "test-bootstrap-token")

import pytest
from sqlalchemy import event
from sqlalchemy.pool import StaticPool

from app import create_app
from app.extensions import db
from app.orgs.service import create_organization


@pytest.fixture()
def app(tmp_path):
    app = create_app()
    app.config.update(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "AUDIT_SECRET": "test-audit-chain-secret",
            "LOCAL_AUTH_ENABLED": True,
            "OIDC_ENABLED": False,
            "SECRET_ENCRYPTION_KEY": "",
            "REQUIREMENT_ANALYSIS_PROVIDER": "rules",
            "AGENT_IMPLEMENTATION_PROVIDER": "disabled",
            "GIT_KEY_DIR": str(tmp_path / "gitkeys"),
            "GIT_KNOWN_HOSTS": str(tmp_path / "git" / "known_hosts"),
            "SANDBOX_WORKSPACE_DIR": str(tmp_path / "workspaces"),
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SQLALCHEMY_ENGINE_OPTIONS": {
                "poolclass": StaticPool,
                "connect_args": {"check_same_thread": False},
            },
        }
    )

    from app.git.adapter import GitAdapter
    from app.git.backend import FakeGitBackend

    app.config["GIT_ADAPTER_FACTORY"] = lambda: GitAdapter(
        "ssh",
        str(tmp_path / "adapterkeys"),
        str(tmp_path / "adapterhosts"),
        backend=FakeGitBackend(),
    )
    with app.app_context():

        @event.listens_for(db.engine, "connect")
        def _enable_fk(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        db.create_all()
        # The context stays alive for the whole test; nested pushes would
        # detach ORM instances on pop, so fixtures/tests must not nest one.
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def org(app):
    return create_organization("Test Org", slug="test")


@pytest.fixture()
def admin(app, org):
    from app.auth.providers.local import LocalProvider

    return LocalProvider(org.slug).ensure_local_user(
        "admin@test.local", "password123", "Admin User", ["organization_administrator"]
    )


@pytest.fixture()
def developer(app, org):
    from app.auth.providers.local import LocalProvider

    return LocalProvider(org.slug).ensure_local_user(
        "dev@test.local", "password123", "Dev User", ["developer"]
    )


@pytest.fixture()
def login(client, org, admin):
    def _login(email="admin@test.local", password="password123"):
        return client.post(
            "/api/v1/auth/login",
            json={
                "email": email,
                "password": password,
                "organization": org.slug,
            },
        ).get_json()["data"]["token"]

    return _login


@pytest.fixture()
def auth_headers(login):
    def _headers(token=None):
        return {"Authorization": f"Bearer {token or login()}"}

    return _headers
