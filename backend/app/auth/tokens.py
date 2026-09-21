import hashlib
import secrets
from datetime import timedelta

from ..extensions import db
from ..models import Token, User
from ..utils import utcnow


def create_token(user: User, ttl_seconds: int) -> tuple[str, Token]:
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    token = Token(
        organization_id=user.organization_id,
        user_id=user.id,
        token_hash=digest,
        expires_at=utcnow() + timedelta(seconds=ttl_seconds),
    )
    db.session.add(token)
    db.session.commit()
    return raw, token


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def revoke_token(token: Token) -> None:
    token.revoked_at = utcnow()
    db.session.commit()


def is_valid(token: Token) -> bool:
    if token.revoked_at is not None:
        return False
    if token.expires_at and token.expires_at <= utcnow():
        return False
    return True


def touch(token: Token) -> None:
    token.last_used_at = utcnow()
    db.session.add(token)
    db.session.commit()
