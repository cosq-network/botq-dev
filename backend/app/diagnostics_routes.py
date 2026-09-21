from flask import Blueprint, g

from .api.responses import ok
from .auth.roles import has_scope
from .diagnostics import build_diagnostic_report
from .errors import AuthenticationError, AuthorizationError
from .retention import build_retention_plan, execute_retention

bp = Blueprint("diagnostics", __name__, url_prefix="/diagnostics")


@bp.get("/bundle")
def bundle():
    _require_scope("audit:read")
    return ok(build_diagnostic_report(g.organization.id))


@bp.get("/retention-plan")
def retention_plan():
    _require_scope("audit:read")
    return ok(build_retention_plan(g.organization.id))


@bp.post("/retention/execute")
def retention_execute():
    _require_scope("admin")
    from flask import request

    payload = request.get_json(silent=True) or {}
    dry_run = payload.get("dry_run", True) is not False
    if not dry_run and payload.get("confirm") is not True:
        raise AuthorizationError("Retention deletion requires confirm=true")
    return ok(execute_retention(g.organization.id, dry_run=dry_run))


def _require_scope(scope: str) -> None:
    if g.get("user") is None:
        raise AuthenticationError()
    if not has_scope(g.user, scope):
        raise AuthorizationError(f"{scope} scope required")
