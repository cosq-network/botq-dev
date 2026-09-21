"""Shared versioning and hashing for architecture and planning artifacts."""

import hashlib
import json

from ..errors import NotFoundError, ValidationError
from ..models import Artifact, ArtifactVersion
from ..utils import new_uuid

ARTIFACT_TYPES = {"architecture", "technical_plan", "mockup"}
SUBMITTABLE_STATUSES = {"draft", "changes_requested", "rejected"}


def content_hash(content: dict) -> str:
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_content(raw) -> dict:
    if not isinstance(raw, dict):
        raise ValidationError("content must be an object")
    if not raw:
        raise ValidationError("content must not be empty")
    return raw


def serialize_version(version: ArtifactVersion, *, include_content: bool = True) -> dict:
    data = {
        "id": str(version.id),
        "artifact_id": str(version.artifact_id),
        "version": version.version,
        "content_hash": version.content_hash,
        "change_summary": version.change_summary,
        "created_by": version.created_by,
        "created_at": version.created_at.isoformat(),
    }
    if include_content:
        data["content"] = version.content
    return data


def current_version(artifact: Artifact) -> ArtifactVersion:
    for version in artifact.versions:
        if version.version == artifact.current_version:
            return version
    raise NotFoundError("Current artifact version not found")


def serialize_artifact(artifact: Artifact, *, include_content: bool = False) -> dict:
    version = current_version(artifact)
    data = {
        "id": str(artifact.id),
        "project_id": str(artifact.project_id),
        "artifact_type": artifact.artifact_type,
        "title": artifact.title,
        "status": artifact.status,
        "current_version": artifact.current_version,
        "current_hash": version.content_hash,
        "version_count": len(artifact.versions),
        "created_by": artifact.created_by,
        "created_at": artifact.created_at.isoformat(),
        "updated_at": artifact.updated_at.isoformat(),
    }
    if include_content:
        data["content"] = version.content
    return data


def new_artifact(*, organization_id, project_id, artifact_type, title, content, created_by):
    if artifact_type not in ARTIFACT_TYPES:
        raise ValidationError(f"artifact_type must be one of: {', '.join(sorted(ARTIFACT_TYPES))}")
    content = normalize_content(content)
    artifact = Artifact(
        id=new_uuid(),
        organization_id=organization_id,
        project_id=project_id,
        artifact_type=artifact_type,
        title=title,
        status="draft",
        current_version=1,
        created_by=created_by,
    )
    version = ArtifactVersion(
        id=new_uuid(),
        organization_id=organization_id,
        artifact_id=artifact.id,
        version=1,
        content=content,
        content_hash=content_hash(content),
        change_summary="initial version",
        created_by=created_by,
    )
    return artifact, version


def new_artifact_version(
    *, artifact: Artifact, content: dict, created_by: str, change_summary: str
):
    """Build an immutable next version without mutating the current version row."""
    content = normalize_content(content)
    return ArtifactVersion(
        id=new_uuid(),
        organization_id=artifact.organization_id,
        artifact_id=artifact.id,
        version=artifact.current_version + 1,
        content=content,
        content_hash=content_hash(content),
        change_summary=change_summary[:500],
        created_by=created_by,
    )
