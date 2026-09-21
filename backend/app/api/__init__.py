from flask import Blueprint, request

from ..auth.decorators import load_context
from ..errors import AuthenticationError

api = Blueprint("api", __name__, url_prefix="/api/v1")

PUBLIC_ENDPOINTS = {
    "api.ping",
    "api.auth.login_local",
    "api.auth.list_providers",
    "api.auth.oidc_login",
    "api.auth.oidc_callback",
    "api.orgs.create_org",
    "api.orgs.list_orgs",
}


@api.before_request
def _require_authentication():
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    try:
        load_context()
    except AuthenticationError:
        raise
    return None


from ..approvals.routes import bp as approvals_bp  # noqa: E402
from ..architecture.routes import bp as architecture_bp  # noqa: E402
from ..audit.routes import bp as audit_bp  # noqa: E402
from ..auth.routes import bp as auth_bp  # noqa: E402
from ..design.routes import bp as design_bp  # noqa: E402
from ..diagnostics_routes import bp as diagnostics_bp  # noqa: E402
from ..gates.routes import bp as gates_bp  # noqa: E402
from ..git.routes import bp as git_bp  # noqa: E402
from ..orgs.routes import bp as orgs_bp  # noqa: E402
from ..planning.routes import bp as planning_bp  # noqa: E402
from ..projects.routes import bp as projects_bp  # noqa: E402
from ..release.routes import bp as release_bp  # noqa: E402
from ..requirements.routes import bp as requirements_bp  # noqa: E402
from ..sandbox.routes import bp as sandbox_bp  # noqa: E402
from ..secrets.routes import bp as secrets_bp  # noqa: E402
from ..traceability.routes import bp as traceability_bp  # noqa: E402
from ..work_items.routes import bp as work_items_bp  # noqa: E402

api.register_blueprint(auth_bp)
api.register_blueprint(design_bp)
api.register_blueprint(diagnostics_bp)
api.register_blueprint(orgs_bp)
api.register_blueprint(projects_bp)
api.register_blueprint(release_bp)
api.register_blueprint(requirements_bp)
api.register_blueprint(architecture_bp)
api.register_blueprint(planning_bp)
api.register_blueprint(traceability_bp)
api.register_blueprint(approvals_bp)
api.register_blueprint(work_items_bp)
api.register_blueprint(git_bp)
api.register_blueprint(gates_bp)
api.register_blueprint(secrets_bp)
api.register_blueprint(sandbox_bp)
api.register_blueprint(audit_bp)


@api.get("/ping")
def ping():
    from .responses import ok

    return ok({"service": "botq", "version": "0.1.0"})
