import logging
import os

import click
from flask import Flask, g, render_template

from .config import Config
from .extensions import db, migrate
from .utils import new_uuid

SECRET_FIELDS = ("password", "secret", "token", "key", "credential", "authorization")


class RedactingFilter(logging.Filter):
    def filter(self, record):
        try:
            msg = record.getMessage()
            if isinstance(msg, str):
                lowered = msg.lower()
                for field in SECRET_FIELDS:
                    if field in lowered:
                        record.msg = "[REDACTED]"
                        record.args = ()
                        break
        except Exception as exc:
            record.msg = "[REDACTED]"
            record.args = ()
            logging.getLogger(__name__).debug("Log redaction failed: %s", type(exc).__name__)
        return True


def create_app(config_object=None):
    app = Flask(__name__, template_folder="templates")
    app.config.from_object(config_object or Config)
    if app.config.get("ENVIRONMENT", "").lower() == "production":
        insecure = {
            "SECRET_KEY": "change-me-in-production",  # nosec B105 - sentinel default.
            "AUDIT_SECRET": "change-me-audit-chain-secret",  # nosec B105 - sentinel default.
        }
        for name, default in insecure.items():
            if app.config.get(name) == default:
                raise RuntimeError(f"{name} must be configured in production")
        encryption_key = app.config.get("SECRET_ENCRYPTION_KEY", "")
        if not encryption_key:
            raise RuntimeError("SECRET_ENCRYPTION_KEY must be configured in production")
        try:
            from cryptography.fernet import Fernet

            Fernet(encryption_key.encode())
        except Exception as exc:
            raise RuntimeError("SECRET_ENCRYPTION_KEY must be a valid Fernet key") from exc
        if not app.config.get("RATE_LIMIT_ENABLED") or app.config.get("RATE_LIMIT_BACKEND") != "redis":
            raise RuntimeError(
                "Production rate limiting must be enabled with RATE_LIMIT_BACKEND=redis"
            )
        if "host" in app.config.get("SANDBOX_NETWORK_ALLOWLIST", []):
            raise RuntimeError("Host sandbox networking is not allowed in production")
        if app.config.get("BOOTSTRAP_ENABLED") and not app.config.get("BOOTSTRAP_TOKEN"):
            raise RuntimeError("BOOTSTRAP_TOKEN is required when production bootstrap is enabled")
    app.config["DEFAULT_ORG_SLUG"] = os.environ.get("DEFAULT_ORG_SLUG", "cdx")

    _configure_logging(app)

    from . import observability

    observability.initialize(app)

    db.init_app(app)
    migrate.init_app(app, db)

    from . import models as _models  # noqa: F401
    from .models import register_audit_guards, register_immutability_guards

    register_audit_guards()
    register_immutability_guards()

    from .api import api
    from .api.health import hp
    from .api.openapi import docs_bp

    app.register_blueprint(api)
    app.register_blueprint(hp)
    app.register_blueprint(docs_bp)

    from .errors import register_error_handlers

    register_error_handlers(app)

    from .backup.cli import backup_cli

    app.cli.add_command(backup_cli)

    @app.before_request
    def _correlation():
        from flask import request

        g.correlation_id = request.headers.get("X-Correlation-ID") or new_uuid().hex
        observability.before_request()

    app.after_request(observability.after_request)

    @app.get("/")
    def index():
        return render_template("index.html", app_name=app.config["APP_NAME"])

    @app.get("/workbench")
    def workbench():
        return render_template("workbench.html", app_name=app.config["APP_NAME"])

    @app.cli.command("bootstrap")
    @click.option("--org-name", default="COSQ Network")
    @click.option("--slug", default=None)
    @click.option("--email", default="admin@local")
    @click.option("--password", default="admin-change-me")
    def bootstrap(org_name, slug, email, password):
        with app.app_context():
            from werkzeug.security import generate_password_hash

            from .models import Organization, User
            from .orgs.service import create_organization, roles_for_org

            org = Organization.query.filter_by(slug=slug or "cdx").first()
            if org is None:
                org = create_organization(org_name, slug)
            roles = roles_for_org(org.id)
            user = User.query.filter_by(organization_id=org.id, email=email.lower()).first()
            if user is None:
                user = User(
                    id=new_uuid(),
                    organization_id=org.id,
                    email=email.lower(),
                    display_name="Organization Admin",
                    password_hash=generate_password_hash(password),
                )
                db.session.add(user)
                db.session.flush()
            admin_role = roles.get("organization_administrator")
            if admin_role and admin_role not in user.roles:
                user.roles.append(admin_role)
            db.session.commit()
            click.echo(f"Organization: {org.name} ({org.slug})")
            click.echo(f"User: {user.email} roles={[r.name for r in user.roles]}")
        return None

    return app


def _configure_logging(app: Flask) -> None:
    level = getattr(logging, app.config.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.addFilter(RedactingFilter())

    app.logger.setLevel(level)
    if not _has_redacting_handler(app.logger):
        app.logger.addHandler(handler)
    app.logger.propagate = False

    root = logging.getLogger()
    root.setLevel(level)
    if not _has_redacting_handler(root):
        root.addHandler(handler)


def _has_redacting_handler(logger: logging.Logger) -> bool:
    return any(
        isinstance(f, RedactingFilter) for h in logger.handlers for f in getattr(h, "filters", [])
    )
