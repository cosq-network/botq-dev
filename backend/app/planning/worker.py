"""Durable Phase 3 agent-run worker.

Runs are claimed in the database, resumed from the latest checkpoint, and
converted into draft change sets. The worker deliberately stops at a human-
reviewable change set; approval and verification remain separate gates.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import socket
import time
from datetime import timedelta

from sqlalchemy import or_

from ..artifacts import service
from ..audit.service import record_audit
from ..errors import ConflictError
from ..extensions import db
from ..models import AgentCheckpoint, AgentRun, AgentRunEvent, Artifact, ChangeSet, ChangeSetFile
from ..observability import metrics
from ..utils import new_uuid, utcnow
from .executor import (
    AgentExecutionError,
    ManagedInferenceAgentExecutor,
    validate_diff_against_snapshot,
)


class WorkerLeaseLost(ConflictError):
    def __init__(self):
        super().__init__(
            "The agent-run lease is no longer owned by this worker",
            code="worker_lease_lost",
        )


class AgentRunWorker:
    def __init__(self, app, worker_id: str | None = None):
        self.app = app
        self.worker_id = worker_id or f"{socket.gethostname()}:{new_uuid().hex[:12]}"

    def process_once(self) -> bool:
        """Claim and process one queued run. Return whether work was found."""
        with self.app.app_context():
            started = time.perf_counter()
            run = self._claim()
            if run is None:
                metrics().increment("agent_run_polls_total", labels={"result": "empty"})
                return False
            try:
                self._execute(run)
            except Exception as exc:  # the run must become observable, never disappear
                db.session.rollback()
                current = AgentRun.query.filter_by(id=run.id).first()
                if (
                    current is not None
                    and current.worker_id == self.worker_id
                    and current.status not in {"cancelled", "paused"}
                ):
                    current.status = "failed"
                    current.pause_reason = str(exc)[:1000]
                    current.lease_expires_at = None
                    self._event(current, "run_failed", {"error": str(exc)[:1000]})
                    db.session.commit()
                    record_audit(
                        action="agent_run.failed",
                        actor_type="worker",
                        actor_id=self.worker_id,
                        target_type="agent_run",
                        target_id=current.id,
                        organization_id=current.organization_id,
                        metadata={"error": str(exc)[:1000]},
                    )
                metrics().increment("agent_runs_total", labels={"status": "failed"})
                metrics().observe("agent_run_duration_ms", (time.perf_counter() - started) * 1000)
                return True
            metrics().increment("agent_runs_total", labels={"status": run.status})
            metrics().observe("agent_run_duration_ms", (time.perf_counter() - started) * 1000)
            return True

    def _claim(self):
        now = utcnow()
        query = (
            AgentRun.query.filter(
                AgentRun.status.in_({"queued", "running"}),
                or_(AgentRun.lease_expires_at.is_(None), AgentRun.lease_expires_at <= now),
            )
            .order_by(AgentRun.created_at.asc())
            .with_for_update(skip_locked=True)
        )
        run = query.first()
        if run is None:
            return None
        run.status = "running"
        run.worker_id = self.worker_id
        run.attempt_count += 1
        run.lease_expires_at = now + timedelta(
            seconds=int(self.app.config.get("AGENT_WORKER_LEASE_SECONDS", 900))
        )
        self._event(run, "run_claimed", {"worker_id": self.worker_id, "attempt": run.attempt_count})
        db.session.commit()
        return run

    def _execute(self, run):
        plan = Artifact.query.filter_by(
            id=run.plan_artifact_id,
            organization_id=run.organization_id,
            artifact_type="technical_plan",
            status="approved",
        ).first()
        if plan is None:
            raise ConflictError("The approved plan is no longer available", code="stale_plan")
        plan_version = service.current_version(plan)
        if plan.current_version != run.plan_version or plan_version.content_hash != run.plan_hash:
            raise ConflictError("The plan changed after this run was created", code="stale_plan")
        self._assert_lease(run)

        checkpoint = run.checkpoints[-1].state if run.checkpoints else None
        if self._operator_stopped(run):
            return
        factory = self.app.config.get("AGENT_RUN_EXECUTOR_FACTORY")
        executor = (
            factory(self.app, run)
            if factory
            else ManagedInferenceAgentExecutor(self.app.config, run.model_config)
        )
        result = executor.execute(run, plan_version.content, checkpoint)
        if self._operator_stopped(run):
            return
        self._assert_lease(run)

        changes = []
        runtime = run.environment if isinstance(run.environment, dict) else {}
        snapshot = str(runtime.get("repository_snapshot") or "")
        for change in result.changes:
            path = _safe_path(change.path)
            if not _path_allowed(path, run.writable_paths):
                raise ConflictError(
                    f"Provider proposed path outside the approved writable boundary: {path}",
                    code="path_out_of_scope",
                )
            validate_diff_against_snapshot(change.diff, path, snapshot)
            changes.append((path, change.action, change.diff))
        if not changes:
            raise AgentExecutionError("Provider returned no usable changes")

        branch = str(runtime.get("branch") or f"agent/{run.id}").strip()
        base_commit = str(runtime.get("base_commit") or "").strip()
        if not base_commit:
            raise AgentExecutionError(
                "Agent run environment must include base_commit before a change set can be created"
            )
        change_set = ChangeSet(
            id=new_uuid(),
            organization_id=run.organization_id,
            project_id=run.project_id,
            run_id=run.id,
            plan_artifact_id=run.plan_artifact_id,
            plan_version=run.plan_version,
            plan_hash=run.plan_hash,
            branch=branch,
            base_commit=base_commit,
            status="draft",
            self_review=result.self_review,
            created_by=run.created_by,
        )
        db.session.add(change_set)
        db.session.flush()
        for path, action, diff in changes:
            db.session.add(
                ChangeSetFile(
                    id=new_uuid(),
                    organization_id=run.organization_id,
                    change_set_id=change_set.id,
                    path=path,
                    action=action,
                    diff=diff,
                    content_hash=hashlib.sha256(diff.encode("utf-8")).hexdigest(),
                )
            )
        db.session.flush()
        self._assert_lease(run)
        change_set.diff_hash = _change_set_hash(change_set)
        checkpoint_state = {
            "status": "change_set_created",
            "change_set_id": str(change_set.id),
            "provider": result.provider,
            "change_count": len(changes),
        }
        db.session.add(
            AgentCheckpoint(
                id=new_uuid(),
                organization_id=run.organization_id,
                run_id=run.id,
                sequence=(run.checkpoints[-1].sequence if run.checkpoints else 0) + 1,
                state=checkpoint_state,
                evidence=result.evidence,
            )
        )
        run.current_step = "change_set_review"
        run.status = "completed"
        run.lease_expires_at = None
        self._event(run, "change_set_created", checkpoint_state)
        db.session.commit()
        record_audit(
            action="agent_run.completed",
            actor_type="worker",
            actor_id=self.worker_id,
            target_type="agent_run",
            target_id=run.id,
            organization_id=run.organization_id,
            metadata={"change_set_id": str(change_set.id), "provider": result.provider},
        )

    @staticmethod
    def _operator_stopped(run) -> bool:
        db.session.expire(run)
        db.session.refresh(run)
        return run.status in {"paused", "cancelled"}

    def _assert_lease(self, run):
        db.session.expire(run)
        db.session.refresh(run)
        if (
            run.status != "running"
            or run.worker_id != self.worker_id
            or run.lease_expires_at is None
            or run.lease_expires_at <= utcnow()
        ):
            raise WorkerLeaseLost()

    @staticmethod
    def _event(run, event_type, payload):
        sequence = (run.events[-1].sequence if run.events else 0) + 1
        db.session.add(
            AgentRunEvent(
                id=new_uuid(),
                organization_id=run.organization_id,
                run_id=run.id,
                sequence=sequence,
                event_type=event_type,
                payload=payload,
            )
        )


def _change_set_hash(change_set):
    content = [
        {"path": item.path, "action": item.action, "content_hash": item.content_hash}
        for item in change_set.files
    ]
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _safe_path(value):
    path = str(value or "").replace("\\", "/")
    if not path or path.startswith(("/", "~")):
        raise AgentExecutionError("Provider returned an absolute or empty path")
    normalized = posixpath.normpath(path)
    if normalized in {".", ".."} or normalized.startswith("../"):
        raise AgentExecutionError("Provider returned a path outside the workspace")
    return normalized


def _path_allowed(path, allowed):
    return bool(allowed) and any(
        path == prefix or path.startswith(prefix.rstrip("/") + "/") for prefix in allowed
    )
