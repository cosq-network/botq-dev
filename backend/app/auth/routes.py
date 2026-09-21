import secrets
from urllib.parse import urlencode

from flask import Blueprint, current_app, g, redirect, request, session, url_for

from ..api.responses import error_response, ok
from ..audit.service import record_audit
from ..errors import AuthenticationError, ValidationError
from ..models import Token, User
from .decorators import require_auth
from .providers.local import LocalProvider
from .roles import scopes_for_user
from .tokens import create_token, revoke_token

bp = Blueprint("auth", __name__, url_prefix="/auth")


def _providers_available():
    providers: list[dict] = []
    if current_app.config["LOCAL_AUTH_ENABLED"]:
        providers.append({"name": "local", "login_url": url_for("api.auth.login_local")})
    if current_app.config["OIDC_ENABLED"]:
        providers.append({"name": "oidc", "login_url": url_for("api.auth.oidc_login")})
    return providers


@bp.get("/providers")
def list_providers():
    return ok(_providers_available())


@bp.post("/login")
def login_local():
    if not current_app.config["LOCAL_AUTH_ENABLED"]:
        raise AuthenticationError("Local authentication is disabled")
    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip()
    password = payload.get("password") or ""
    if not email or not password:
        raise ValidationError("email and password are required")
    provider = LocalProvider(
        org_slug=payload.get("organization") or current_app.config.get("DEFAULT_ORG_SLUG", "cdx")
    )
    user = provider.authenticate(email, password)
    if user is None:
        record_audit(
            action="auth.login.failed",
            actor_type="user",
            actor_id=email,
            target_type="user",
            metadata={"reason": "invalid_credentials"},
        )
        return error_response("Invalid credentials", "invalid_credentials", 401)
    user.last_login_at = _now()
    raw, token = create_token(user, current_app.config["TOKEN_TTL_SECONDS"])
    record_audit(
        action="auth.login",
        actor_type="user",
        actor_id=user.id,
        target_type="user",
        organization_id=user.organization_id,
        metadata={"provider": "local"},
    )
    return ok(
        {
            "token": raw,
            "expires_in": current_app.config["TOKEN_TTL_SECONDS"],
            "user": _user_payload(user),
            "organization": {
                "id": str(user.organization.id),
                "name": user.organization.name,
                "slug": user.organization.slug,
            },
        }
    )


@bp.post("/logout")
@require_auth
def logout():
    token: Token = g.get("token")
    user: User = g.get("user")
    if token is not None:
        revoke_token(token)
    if hasattr(g, "correlation_id"):
        pass
    if user is not None:
        record_audit(
            action="auth.logout",
            actor_type="user",
            actor_id=user.id,
            target_type="user",
            organization_id=user.organization_id,
        )
    return ok(message="Logged out")


@bp.get("/me")
@require_auth
def me():
    user: User = g.user
    return ok(
        {
            "user": _user_payload(user),
            "scopes": sorted(scopes_for_user(user)),
            "organization": {
                "id": str(g.organization.id),
                "name": g.organization.name,
                "slug": g.organization.slug,
            },
        }
    )


@bp.get("/oidc/login")
def oidc_login():
    if not current_app.config["OIDC_ENABLED"]:
        raise AuthenticationError("OIDC is disabled")
    from .providers.oidc import OIDCProvider

    org_slug = request.args.get("organization") or current_app.config.get("DEFAULT_ORG_SLUG", "cdx")
    session["oidc_organization"] = org_slug
    nonce = secrets.token_urlsafe(32)
    session["oidc_nonce"] = nonce
    oidc = OIDCProvider(current_app)
    redirect_uri = url_for("api.auth.oidc_callback", _external=True)
    return oidc.authorization_url(redirect_uri, nonce=nonce)


@bp.get("/oidc/callback")
def oidc_callback():
    if not current_app.config["OIDC_ENABLED"]:
        raise AuthenticationError("OIDC is disabled")
    org_slug = session.pop("oidc_organization", None) or current_app.config.get(
        "DEFAULT_ORG_SLUG", "cdx"
    )
    nonce = session.pop("oidc_nonce", None)
    if not nonce:
        raise AuthenticationError("Invalid OIDC login state")
    from ..models import Organization

    org = Organization.query.filter_by(slug=org_slug).first()
    if org is None:
        raise AuthenticationError(f"Unknown organization '{org_slug}'")
    from .providers.oidc import OIDCProvider

    oidc = OIDCProvider(current_app)
    user = oidc.authenticate(
        request.args.get("code", ""),
        url_for("api.auth.oidc_callback", _external=True),
        org.id,
        nonce=nonce,
    )
    user.last_login_at = _now()
    raw, token = create_token(user, current_app.config["TOKEN_TTL_SECONDS"])
    record_audit(
        action="auth.login",
        actor_type="user",
        actor_id=user.id,
        target_type="user",
        organization_id=user.organization_id,
        metadata={"provider": "oidc"},
    )
    target = current_app.config.get("OIDC_SUCCESS_REDIRECT_URI", "/")
    if not target.startswith("/") or target.startswith("//"):
        target = "/"
    target = target.split("#", 1)[0]
    fragment = urlencode({"token": raw, "expires_in": current_app.config["TOKEN_TTL_SECONDS"]})
    return redirect(f"{target}#{fragment}")


def _user_payload(user: User) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "roles": [role.name for role in user.roles],
    }


def _now():
    from ..utils import utcnow

    return utcnow()
