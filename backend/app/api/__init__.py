from flask import Blueprint, request
from pydantic import ValidationError

from ..auth.decorators import load_context, validate_cookie_csrf
from ..errors import ApiError, AuthenticationError
from .dtos import request_dto_for

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
        _validate_typed_request()
        return None
    try:
        load_context()
    except AuthenticationError:
        raise
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        validate_cookie_csrf()
    _validate_typed_request()
    return None


def _validate_typed_request() -> None:
    """Validate JSON bodies before a controller reads them."""
    if request.method not in {"POST", "PUT", "PATCH"}:
        return
    from flask import current_app

    view = current_app.view_functions.get(request.endpoint)
    model = request_dto_for(request.endpoint or "request", view)
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ApiError(
            "Request body must be a JSON object",
            code="validation_error",
            status=422,
        )
    try:
        normalized = model.model_validate(payload).model_dump(exclude_none=True)
    except ValidationError as exc:
        raise ApiError(
            "Request body failed DTO validation",
            code="validation_error",
            status=422,
            details={"fields": exc.errors(include_url=False, include_input=False)},
        ) from exc
    # Preserve the existing controller API while ensuring every subsequent
    # request.get_json() call receives the validated DTO representation.
    request._cached_json = (normalized, normalized)


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
