"""Safe, tenant-scoped operational diagnostics."""

from __future__ import annotations

from sqlalchemy import func

from .audit.service import verify_chain
from .extensions import db
from .models import AgentRun, AuditEvent, Deployment, Project
from .observability import metrics
from .utils import utcnow


def build_diagnostic_report(organization_id) -> dict:
    """Return a support bundle containing metadata, counts, and health only."""

    report = {
        "format": "botq-diagnostic-bundle",
        "version": 1,
        "generated_at": utcnow().isoformat(),
        "organization_id": str(organization_id),
        "application": {
            "environment": _config("ENVIRONMENT"),
            "version": "0.1.0",
            "providers_configured": {
                "heroku_inference": bool(_config("HEROKU_INFERENCE_BASE_URL")),
                "runpod_inference": bool(_config("RUNPOD_INFERENCE_URL")),
                "openai_compatible_inference": bool(_config("OPENAI_COMPATIBLE_BASE_URL")),
                "preview_deployment": bool(_config("PREVIEW_DEPLOYMENT_URL")),
                "deployment": bool(_config("DEPLOYMENT_URL")),
            },
        },
        "database": {
            "projects": _count(Project, organization_id),
            "audit_events": _count(AuditEvent, organization_id),
            "agent_runs": _count(AgentRun, organization_id),
            "deployments": _count(Deployment, organization_id),
        },
        "agent_runs": _status_counts(AgentRun, organization_id),
        "deployments": _status_counts(Deployment, organization_id),
        "audit_chain": _audit_health(organization_id),
        "metrics": metrics().snapshot(),
        "redaction": {
            "included": ["statuses", "counts", "provider-presence", "audit-integrity"],
            "excluded": ["request-bodies", "headers", "tokens", "secrets", "model-prompts"],
        },
    }
    return report


def _config(name: str):
    from flask import current_app

    return current_app.config.get(name, "")


def _count(model, organization_id) -> int:
    return (
        db.session.query(func.count(model.id)).filter_by(organization_id=organization_id).scalar()
        or 0
    )


def _status_counts(model, organization_id) -> dict:
    rows = (
        db.session.query(model.status, func.count(model.id))
        .filter_by(organization_id=organization_id)
        .group_by(model.status)
        .all()
    )
    return {status: count for status, count in rows}


def _audit_health(organization_id) -> dict:
    try:
        result = verify_chain(organization_id)
    except Exception as exc:  # diagnostics must remain available during incidents
        return {"status": "error", "detail": type(exc).__name__}
    return {
        "status": "valid" if result.get("verified") else "invalid",
        "events": result.get("total", 0),
        "verified_count": result.get("verified_count", 0),
    }
