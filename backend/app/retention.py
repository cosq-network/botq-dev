"""Retention policy inspection and safe, non-destructive planning."""

from datetime import timedelta

from .audit.service import record_audit
from .extensions import db
from .models import AgentCheckpoint, AgentRunEvent, AuditEvent
from .utils import utcnow


def build_retention_plan(organization_id) -> dict:
    """Calculate eligible records without deleting anything.

    Audit events are intentionally reported but not auto-purged: deleting a
    prefix of a hash chain requires an archive/re-seal procedure and an
    explicit retention authority decision.
    """

    now = utcnow()
    policies = {
        "audit_events": (AuditEvent, "RETENTION_AUDIT_DAYS", False),
        "agent_run_events": (AgentRunEvent, "RETENTION_AGENT_EVENT_DAYS", True),
        "agent_checkpoints": (AgentCheckpoint, "RETENTION_CHECKPOINT_DAYS", True),
    }
    items = {}
    for name, (model, config_key, purgeable) in policies.items():
        days = int(_config(config_key))
        cutoff = now - timedelta(days=days)
        query = model.query.filter(
            model.organization_id == organization_id, model.created_at < cutoff
        )
        items[name] = {
            "retention_days": days,
            "cutoff": cutoff.isoformat(),
            "eligible": query.count(),
            "purgeable_by_automation": purgeable,
        }
    return {
        "generated_at": now.isoformat(),
        "organization_id": str(organization_id),
        "items": items,
        "mode": "plan_only",
        "note": "No records were deleted; audit-chain retention requires archival and re-sealing.",
    }


def execute_retention(organization_id, *, dry_run: bool = True) -> dict:
    """Purge only approved non-audit operational records and retain an audit trail."""
    plan = build_retention_plan(organization_id)
    deleted = {}
    for name, model in (
        ("agent_run_events", AgentRunEvent),
        ("agent_checkpoints", AgentCheckpoint),
    ):
        item = plan["items"][name]
        if dry_run:
            deleted[name] = 0
            continue
        cutoff = utcnow() - timedelta(days=item["retention_days"])
        deleted[name] = model.query.filter(
            model.organization_id == organization_id, model.created_at < cutoff
        ).delete(synchronize_session=False)
    if not dry_run:
        record_audit(
            action="retention.executed",
            target_type="retention_policy",
            target_id=str(organization_id),
            organization_id=organization_id,
            metadata={"deleted": deleted, "audit_events_preserved": True},
            commit=False,
        )
        db.session.commit()
    return {**plan, "mode": "dry_run" if dry_run else "executed", "deleted": deleted}


def _config(name: str):
    from flask import current_app

    return current_app.config[name]
