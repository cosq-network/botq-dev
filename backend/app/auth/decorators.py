import functools

from flask import g, request

from ..errors import AuthenticationError, AuthorizationError
from ..models import Organization, Token, User
from .roles import has_scope
from .tokens import hash_token, is_valid, touch


def _bearer_token() -> str | None:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def load_context() -> Token:
    raw = _bearer_token()
    if not raw:
        raise AuthenticationError("Missing bearer token")
    token = Token.query.filter_by(token_hash=hash_token(raw)).first()
    if token is None or not is_valid(token):
        raise AuthenticationError("Invalid or expired token")
    user = User.query.get(token.user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("User is not active")
    org = Organization.query.get(token.organization_id)
    if org is None or not org.is_active:
        raise AuthenticationError("Organization is not active")
    g.user = user
    g.organization = org
    g.token = token
    touch(token)
    return token


def require_auth(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        load_context()
        return f(*args, **kwargs)

    return wrapper


def require_scope(scope: str):
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if "user" not in g:
                load_context()
            user = g.get("user")
            if user is None or not has_scope(user, scope):
                raise AuthorizationError(
                    f"Missing required scope: {scope}", details={"scope": scope}
                )
            return f(*args, **kwargs)

        return wrapper

    return decorator


def require_role(*role_names: str):
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if "user" not in g:
                load_context()
            user = g.get("user")
            if user is None:
                raise AuthenticationError()
            current = {role.name for role in user.roles or []}
            if not (current.intersection(role_names)):
                raise AuthorizationError(
                    f"Requires one of roles: {', '.join(role_names)}",
                    details={"roles": list(role_names)},
                )
            return f(*args, **kwargs)

        return wrapper

    return decorator
