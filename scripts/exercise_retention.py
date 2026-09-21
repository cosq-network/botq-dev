"""Exercise retention planning and controlled non-audit cleanup locally."""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from app import create_app
from app.audit.service import record_audit
from app.extensions import db
from app.models import (
    AgentCheckpoint,
    AgentRun,
    AgentRunEvent,
    Artifact,
    ArtifactVersion,
    AuditEvent,
    Project,
)
from app.orgs.service import create_organization
from app.retention import execute_retention
from app.utils import new_uuid, utcnow


def main() -> int:
    output = Path(".pilot-evidence/retention-exercise.json")
    app = create_app()
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite://",
        RETENTION_AUDIT_DAYS=365,
        RETENTION_AGENT_EVENT_DAYS=1,
        RETENTION_CHECKPOINT_DAYS=1,
        TESTING=True,
    )
    with app.app_context():
        db.drop_all()
        db.create_all()
        org = create_organization("Retention Evidence", slug="retention-evidence")
        project = Project(
            id=new_uuid(), organization_id=org.id, name="Retention Pilot", key="RET",
        )
        db.session.add(project)
        db.session.flush()
        artifact = Artifact(
            id=new_uuid(), organization_id=org.id, project_id=project.id,
            artifact_type="plan", title="Retention plan", status="approved",
            current_version=1,
        )
        db.session.add(artifact)
        db.session.flush()
        db.session.add(ArtifactVersion(
            id=new_uuid(), organization_id=org.id, artifact_id=artifact.id,
            version=1, content={"steps": []}, content_hash="a" * 64,
        ))
        run = AgentRun(
            id=new_uuid(), organization_id=org.id, project_id=project.id,
            plan_artifact_id=artifact.id, plan_version=1, plan_hash="b" * 64,
            objective="retention exercise", status="completed",
        )
        db.session.add(run)
        db.session.flush()
        old = utcnow() - timedelta(days=10)
        event = AgentRunEvent(
            id=new_uuid(), organization_id=org.id, run_id=run.id, sequence=1,
            event_type="completed", payload={"synthetic": True}, created_at=old,
        )
        checkpoint = AgentCheckpoint(
            id=new_uuid(), organization_id=org.id, run_id=run.id, sequence=1,
            state={"synthetic": True}, evidence={}, created_at=old,
        )
        db.session.add_all([event, checkpoint])
        record_audit(
            action="retention.seeded", actor_type="system", organization_id=org.id,
            target_type="retention_exercise", target_id=str(run.id),
            metadata={"synthetic": True}, commit=False,
        )
        db.session.commit()

        before = {
            "run_events": AgentRunEvent.query.filter_by(organization_id=org.id).count(),
            "checkpoints": AgentCheckpoint.query.filter_by(organization_id=org.id).count(),
            "audit_events": AuditEvent.query.filter_by(organization_id=org.id).count(),
        }
        dry_run = execute_retention(org.id, dry_run=True)
        after_dry_run = {
            "run_events": AgentRunEvent.query.filter_by(organization_id=org.id).count(),
            "checkpoints": AgentCheckpoint.query.filter_by(organization_id=org.id).count(),
            "audit_events": AuditEvent.query.filter_by(organization_id=org.id).count(),
        }
        executed = execute_retention(org.id, dry_run=False)
        after_execution = {
            "run_events": AgentRunEvent.query.filter_by(organization_id=org.id).count(),
            "checkpoints": AgentCheckpoint.query.filter_by(organization_id=org.id).count(),
            "audit_events": AuditEvent.query.filter_by(organization_id=org.id).count(),
        }
        result = {
            "before": before,
            "dry_run": dry_run,
            "after_dry_run": after_dry_run,
            "executed": executed,
            "after_execution": after_execution,
            "ok": (
                dry_run["mode"] == "dry_run"
                and after_dry_run == before
                and executed["deleted"] == {"agent_run_events": 1, "agent_checkpoints": 1}
                and after_execution["run_events"] == 0
                and after_execution["checkpoints"] == 0
                and after_execution["audit_events"] >= before["audit_events"] + 1
            ),
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True, default=str))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
