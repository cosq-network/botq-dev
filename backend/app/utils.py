import re
import uuid
from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


_COPYRIGHT_RE = re.compile(r"^[a-zA-Z0-9 _./:-]{2,120}$")


def validate_slug(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", value))


def validate_name(value: str) -> bool:
    return bool(value) and len(value.strip()) <= 120


def split_ssh_url(url: str):
    if "://" in url:
        scheme, rest = url.split("://", 1)
        if scheme not in {"ssh", "git"}:
            raise ValueError("Unsupported git URL scheme")
        return rest, None
    if "@" in url and ":" in url:
        host_port, _ = url.rsplit(":", 1)
        _, host = host_port.rsplit("@", 1)
        return url, host
    raise ValueError("Unsupported git SSH URL format")


def host_from_ssh_url(url: str) -> str | None:
    try:
        _, host = split_ssh_url(url)
    except ValueError:
        return None
    if host:
        return host.split(":")[0] if ":" in host else host
    if "://" in url:
        rest = url.split("://", 1)[1]
        return rest.split("/")[0]
    return None
