"""OpenAPI response DTO schemas for the domain resources.

The API envelope remains stable, while each operation gets a named response
schema whose ``data`` member points at the domain payload returned by that
controller.  These are transport contracts; authorization and lifecycle rules
remain in the feature services.
"""

from __future__ import annotations

from typing import Any


def ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def array(name: str) -> dict[str, Any]:
    return {"type": "array", "items": ref(name)}


def obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


STRING = {"type": "string"}
BOOL = {"type": "boolean"}
INTEGER = {"type": "integer"}
JSON = {"type": "object", "additionalProperties": True}

DOMAIN_SCHEMAS: dict[str, dict[str, Any]] = {
    "UserResponse": obj({"id": STRING, "email": STRING, "display_name": STRING, "roles": {"type": "array", "items": STRING}, "is_active": BOOL, "user_type": STRING}),
    "OrganizationResponse": obj({"id": STRING, "name": STRING, "slug": STRING, "settings": JSON}),
    "ProjectResponse": obj({"id": STRING, "name": STRING, "key": STRING, "description": STRING, "lifecycle_state": STRING, "default_branch": STRING, "archived": BOOL, "created_at": STRING, "updated_at": STRING, "repository": JSON}),
    "BaselineResponse": obj({"id": STRING, "project_id": STRING, "title": STRING, "status": STRING, "current_version": INTEGER, "content_hash": STRING, "content": JSON, "version_count": INTEGER}),
    "FindingResponse": obj({"id": STRING, "analysis_id": STRING, "category": STRING, "severity": STRING, "blocking": BOOL, "status": STRING, "title": STRING, "description": STRING, "evidence": JSON, "resolution": STRING}),
    "AnalysisResponse": obj({"id": STRING, "project_id": STRING, "baseline_id": STRING, "baseline_version": INTEGER, "baseline_hash": STRING, "status": STRING, "summary": JSON, "proposed_work_items": {"type": "array", "items": JSON}, "findings": array("FindingResponse")}),
    "WorkItemResponse": obj({"id": STRING, "code": STRING, "project_id": STRING, "kind": STRING, "title": STRING, "description": STRING, "status": STRING, "priority": STRING, "risk": STRING, "estimate": INTEGER, "source_baseline_id": STRING, "parent_id": STRING}),
    "ArtifactResponse": obj({"id": STRING, "project_id": STRING, "title": STRING, "status": STRING, "current_version": INTEGER, "content_hash": STRING, "content": JSON, "source_baseline_id": STRING, "source_artifact_id": STRING, "adrs": {"type": "array", "items": JSON}, "comments": {"type": "array", "items": JSON}}),
    "AgentRunResponse": obj({"id": STRING, "project_id": STRING, "plan_artifact_id": STRING, "objective": STRING, "status": STRING, "plan_version": INTEGER, "budget": JSON, "allowed_tools": {"type": "array", "items": STRING}, "writable_paths": {"type": "array", "items": STRING}, "current_step": STRING, "pause_reason": STRING}),
    "ChangeSetResponse": obj({"id": STRING, "project_id": STRING, "run_id": STRING, "plan_id": STRING, "branch": STRING, "base_commit": STRING, "status": STRING, "diff_hash": STRING, "self_review": JSON, "files": {"type": "array", "items": JSON}, "verifications": {"type": "array", "items": JSON}}),
    "MockupResponse": obj({"id": STRING, "project_id": STRING, "title": STRING, "status": STRING, "current_version": INTEGER, "content_hash": STRING, "design_reference": JSON, "comments": {"type": "array", "items": JSON}}),
    "PreviewResponse": obj({"id": STRING, "project_id": STRING, "mockup_artifact_id": STRING, "status": STRING, "url": STRING, "environment": STRING, "expires_at": STRING, "access_policy": JSON}),
    "AcceptanceSessionResponse": obj({"id": STRING, "project_id": STRING, "preview_id": STRING, "status": STRING, "criteria": {"type": "array", "items": JSON}, "results": {"type": "array", "items": JSON}, "evidence": JSON}),
    "DefectResponse": obj({"id": STRING, "project_id": STRING, "title": STRING, "severity": STRING, "status": STRING, "expected": STRING, "actual": STRING, "reproduction_steps": STRING, "attachments": {"type": "array", "items": JSON}}),
    "GateResponse": obj({"id": STRING, "project_id": STRING, "number": INTEGER, "name": STRING, "status": STRING, "required_evidence": {"type": "array", "items": STRING}, "blocking_checks": {"type": "array", "items": STRING}, "missing_decisions": {"type": "array", "items": STRING}, "decisions": {"type": "array", "items": JSON}}),
    "ApprovalResponse": obj({"id": STRING, "artifact_type": STRING, "artifact_id": STRING, "decision": STRING, "decided_by": STRING, "created_at": STRING}),
    "ReleaseResponse": obj({"id": STRING, "project_id": STRING, "change_set_id": STRING, "version": STRING, "commit_sha": STRING, "status": STRING, "readiness": JSON, "package": JSON}),
    "DeploymentPlanResponse": obj({"id": STRING, "release_id": STRING, "environment": STRING, "status": STRING, "content_hash": STRING, "content": JSON}),
    "DeploymentResponse": obj({"id": STRING, "release_id": STRING, "deployment_plan_id": STRING, "environment": STRING, "status": STRING, "provider": STRING, "provider_deployment_id": STRING, "health": JSON}),
    "RepositoryResponse": obj({"id": STRING, "project_id": STRING, "ssh_url": STRING, "host": STRING, "host_fingerprint_verified": BOOL, "scope": STRING, "default_branch": STRING, "status": STRING, "deploy_key_public": STRING, "last_sync_at": STRING, "last_error": STRING}),
    "SecretResponse": obj({"id": STRING, "name": STRING, "purpose": STRING, "secret_store": STRING, "status": STRING, "key_ref": STRING, "last_accessed_at": STRING, "last_rotated_at": STRING}),
    "ResponsibilityResponse": obj({"id": STRING, "project_id": STRING, "user_id": STRING, "user": JSON, "responsibility_type": STRING, "is_primary": BOOL, "segregation_group": STRING, "effective_from": STRING, "effective_until": STRING}),
    "TraceLinkResponse": obj({"id": STRING, "project_id": STRING, "source_type": STRING, "source_id": STRING, "target_type": STRING, "target_id": STRING, "relation": STRING, "created_by": STRING, "created_at": STRING}),
    "HealthResponse": obj({"status": STRING, "database": STRING, "detail": STRING, "environment": STRING}),
    "AuditEventResponse": obj({"id": STRING, "actor_type": STRING, "actor_id": STRING, "action": STRING, "target_type": STRING, "target_id": STRING, "correlation_id": STRING, "result": STRING, "metadata": JSON, "event_hash": STRING, "created_at": STRING}),
    "JsonObjectResponse": JSON,
}

ENTITY_BY_ENDPOINT = {
    "project": "ProjectResponse", "projects": "ProjectResponse", "baseline": "BaselineResponse",
    "analysis": "AnalysisResponse", "finding": "FindingResponse", "work_item": "WorkItemResponse", "architecture": "ArtifactResponse", "plan": "ArtifactResponse", "artifact": "ArtifactResponse", "agent_run": "AgentRunResponse", "change_set": "ChangeSetResponse", "mockup": "MockupResponse", "preview": "PreviewResponse", "acceptance": "AcceptanceSessionResponse", "defect": "DefectResponse", "gate": "GateResponse", "approval": "ApprovalResponse", "release": "ReleaseResponse", "deployment_plan": "DeploymentPlanResponse", "deployment": "DeploymentResponse", "repository": "RepositoryResponse", "secret": "SecretResponse", "responsibility": "ResponsibilityResponse", "trace": "TraceLinkResponse", "health": "HealthResponse", "audit": "AuditEventResponse", "user": "UserResponse", "organization": "OrganizationResponse",
}


def data_schema_for(endpoint: str, rule: str, method: str) -> dict[str, Any]:
    lowered = f"{endpoint} {rule}".lower()
    if "audit" in lowered and "events" in lowered:
        return obj({"total": INTEGER, "limit": INTEGER, "offset": INTEGER, "events": array("AuditEventResponse")})
    if "health" in lowered:
        return ref("HealthResponse")
    if "traceability" in lowered and "search" in lowered:
        return {"type": "array", "items": JSON}
    if "traceability" in lowered and "links" in lowered:
        return array("TraceLinkResponse") if method == "GET" else ref("TraceLinkResponse")
    for token, schema in ENTITY_BY_ENDPOINT.items():
        if token in lowered:
            return array(schema) if method == "GET" and any(word in lowered for word in ("list", "projects", "baselines", "packages", "plans", "releases", "defects", "mockups", "previews", "gates", "deployments", "secrets", "users", "roles")) else ref(schema)
    return ref("JsonObjectResponse")


def operation_response_schema(endpoint: str, rule: str, method: str) -> tuple[str, dict[str, Any]]:
    name = "".join(part.capitalize() for part in endpoint.replace(".", "_").split("_")) + method.title() + "Response"
    return name, {"allOf": [{"$ref": "#/components/schemas/ApiResponse"}], "properties": {"data": data_schema_for(endpoint, rule, method)}}
