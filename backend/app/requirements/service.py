"""Requirement baseline intake: normalization, hashing and version comparison (REQ-REQ-01)."""

import hashlib
import json

from ..errors import ValidationError

PREVIEW_LIMIT = 500

ATTACHMENT_FIELDS = ("name", "url", "sha256", "size")
REPOSITORY_FIELDS = ("url", "ref", "path")


def _require_text(value, field: str, *, required: bool = False) -> str:
    if value is None:
        if required:
            raise ValidationError(f"{field} is required")
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string")
    if len(value) > PREVIEW_LIMIT * 4:
        raise ValidationError(f"{field} is too long")
    return value.strip()


def _normalize_string_list(raw, field: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValidationError(f"{field} must be a list of strings")
    normalized = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ValidationError(f"{field} entries must be non-empty strings")
        normalized.append(item.strip())
    return normalized


def _normalize_records(raw, field: str, allowed: tuple[str, ...]) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValidationError(f"{field} must be a list of objects")
    normalized = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValidationError(f"{field} entries must be objects")
        unknown = sorted(set(item) - set(allowed))
        if unknown:
            raise ValidationError(f"{field} entries contain unsupported keys: {', '.join(unknown)}")
        if not item.get("name") and not item.get("url"):
            raise ValidationError(f"{field} entries require a name or url")
        record = {}
        for key in allowed:
            if item.get(key) in (None, ""):
                continue
            if key == "size":
                if not isinstance(item[key], int) or item[key] < 0:
                    raise ValidationError("attachment size must be a non-negative integer")
                record[key] = item[key]
            else:
                record[key] = _require_text(item[key], f"{field}.{key}")
        normalized.append(record)
    return normalized


def normalize_content(raw) -> dict:
    """Validate and canonicalize a requirement baseline content payload."""
    if not isinstance(raw, dict):
        raise ValidationError("content must be an object")
    content = {
        "goals": _normalize_string_list(raw.get("goals"), "goals"),
        "functional_specifications": _normalize_string_list(
            raw.get("functional_specifications"), "functional_specifications"
        ),
        "constraints": _normalize_string_list(raw.get("constraints"), "constraints"),
        "acceptance_expectations": _normalize_string_list(
            raw.get("acceptance_expectations"), "acceptance_expectations"
        ),
        "attachments": _normalize_records(raw.get("attachments"), "attachments", ATTACHMENT_FIELDS),
        "repository_references": _normalize_records(
            raw.get("repository_references"), "repository_references", REPOSITORY_FIELDS
        ),
    }
    if not content["goals"]:
        raise ValidationError("at least one goal is required")
    return content


def content_hash(content: dict) -> str:
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def diff_contents(old: dict, new: dict) -> dict:
    """Structural diff between two normalized content payloads."""
    old = old or {}
    new = new or {}
    added: dict = {}
    removed: dict = {}
    changed: dict = {}

    for key in sorted(set(old) | set(new)):
        before = old.get(key)
        after = new.get(key)
        if isinstance(before, list) and isinstance(after, list):
            before_missing = [item for item in before if item not in after]
            after_added = [item for item in after if item not in before]
            if before_missing:
                removed[key] = before_missing
            if after_added:
                added[key] = after_added
            continue
        if before == after:
            continue
        if key not in old:
            added[key] = after
        elif key not in new:
            removed[key] = before
        else:
            changed[key] = {"before": before, "after": after}

    return {
        "changed": changed,
        "added": added,
        "removed": removed,
        "material": bool(added or removed or changed),
    }


def summarize_diff(diff: dict) -> str:
    parts = []
    if diff["added"]:
        parts.append(f"added {', '.join(diff['added'])}")
    if diff["removed"]:
        parts.append(f"removed {', '.join(diff['removed'])}")
    if diff["changed"]:
        parts.append(f"changed {', '.join(diff['changed'])}")
    return "; ".join(parts) or "no material change"
