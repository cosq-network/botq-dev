"""Approval loop (REQ-REQ-03, SRS 4.2).

Approvals are immutable records bound to a specific artifact *version + content
hash*. A new version therefore requires a fresh approval. Decisions follow the
SRS vocabulary: Approve / Request changes / Reject / Waive / Cancel. Waive
requires a reason and an expiry. Segregation of duties: the author of an
artifact may never be its approver, and only an ``approval``-scoped reviewer may
record a decision.
"""

from ..errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from ..extensions import db
from ..models import (
    Approval,
    Artifact,
    ChangeSet,
    DeploymentPlan,
    Release,
    RequirementAnalysis,
    RequirementBaseline,
    RequirementFinding,
)
from ..utils import new_uuid, utcnow

DECISIONS = {"approved", "rejected", "changes_requested", "waived", "cancelled"}
REVIEW_DECISIONS = {"approved", "rejected", "changes_requested", "waived"}
# Decisions that grant a gate: the author may never take these on their own work.
SELF_APPROVAL_FORBIDDEN = {"approved", "waived"}

# Statuses from which a gate decision is meaningful for a requirement baseline.
DECISIONABLE_BASELINE = {"submitted"}
CANCELLABLE_BASELINE = {"draft", "submitted", "rejected", "changes_requested", "waived"}
SUPPORTED_VERSIONED_ARTIFACTS = {
    "architecture",
    "technical_plan",
    "mockup",
    "change_set",
    "release",
    "deployment_plan",
}

BASELINE_TRANSITIONS = {
    "approved": "approved",
    "rejected": "rejected",
    "changes_requested": "changes_requested",
    "waived": "waived",
    "cancelled": "cancelled",
}


def resolve_artifact(artifact_type: str, artifact_id, org_id) -> dict:
    """Resolve the current immutable state an approval would bind to."""
    if artifact_type == "requirement_baseline":
        baseline = RequirementBaseline.query.filter_by(
            id=artifact_id, organization_id=org_id
        ).first()
        if baseline is None:
            raise NotFoundError("Requirement baseline not found")
        current = next(
            (v for v in baseline.versions if v.version == baseline.current_version), None
        )
        if current is None:
            raise NotFoundError("Current baseline version not found")
        return {
            "type": artifact_type,
            "id": str(baseline.id),
            "project_id": baseline.project_id,
            "author_id": baseline.created_by,
            "version": baseline.current_version,
            "content_hash": current.content_hash,
            "status": baseline.status,
            "obj": baseline,
        }
    if artifact_type in {"architecture", "technical_plan", "mockup"}:
        artifact = Artifact.query.filter_by(
            id=artifact_id, organization_id=org_id, artifact_type=artifact_type
        ).first()
        if artifact is None:
            raise NotFoundError(f"{artifact_type.replace('_', ' ').title()} not found")
        current = next(
            (v for v in artifact.versions if v.version == artifact.current_version), None
        )
        if current is None:
            raise NotFoundError("Current artifact version not found")
        return {
            "type": artifact_type,
            "id": str(artifact.id),
            "project_id": artifact.project_id,
            "author_id": artifact.created_by,
            "version": artifact.current_version,
            "content_hash": current.content_hash,
            "status": artifact.status,
            "obj": artifact,
        }
    if artifact_type == "change_set":
        change_set = ChangeSet.query.filter_by(id=artifact_id, organization_id=org_id).first()
        if change_set is None:
            raise NotFoundError("Change set not found")
        if not change_set.diff_hash:
            raise ConflictError("Change set has no diff hash", code="change_set_not_ready")
        return {
            "type": artifact_type,
            "id": str(change_set.id),
            "project_id": change_set.project_id,
            "author_id": change_set.created_by,
            "version": 1,
            "content_hash": change_set.diff_hash,
            "status": change_set.status,
            "obj": change_set,
        }
    if artifact_type in {"release", "deployment_plan"}:
        model = Release if artifact_type == "release" else DeploymentPlan
        obj = model.query.filter_by(id=artifact_id, organization_id=org_id).first()
        if obj is None:
            raise NotFoundError(f"{artifact_type.replace('_', ' ').title()} not found")
        return {
            "type": artifact_type,
            "id": str(obj.id),
            "project_id": obj.project_id,
            "author_id": obj.created_by,
            # Releases use a semantic version string for their public identity,
            # while approval bindings are deliberately numeric.  A release is
            # immutable after creation, so revision 1 is the correct approval
            # binding; deployment plans already expose a numeric revision.
            "version": 1 if artifact_type == "release" else obj.version,
            "content_hash": obj.content_hash,
            "status": obj.status,
            "obj": obj,
        }
    raise ValidationError(f"Unsupported artifact type: {artifact_type}")


def _check_binding(info: dict, version, content_hash) -> None:
    if version is not None and int(version) != info["version"]:
        raise ConflictError(
            f"Artifact version changed (now v{info['version']}); re-review the current version",
            code="stale_artifact_version",
        )
    if content_hash and content_hash != info["content_hash"]:
        raise ConflictError(
            "Artifact content hash does not match the current version; approval must bind to "
            "the exact reviewed version",
            code="stale_artifact_hash",
        )


def _check_state_machine(info: dict, decision: str) -> None:
    status = info["status"]
    if info["type"] in SUPPORTED_VERSIONED_ARTIFACTS:
        if decision == "cancelled":
            if status not in CANCELLABLE_BASELINE:
                raise ConflictError(
                    f"Artifact in status '{status}' cannot be cancelled",
                    code="invalid_artifact_state",
                )
            return
        if status not in DECISIONABLE_BASELINE:
            raise ConflictError(
                f"Only a submitted artifact can be reviewed (current status: {status})",
                code="invalid_artifact_state",
            )
        return
    if info["type"] != "requirement_baseline":
        return
    if decision == "cancelled":
        if status not in CANCELLABLE_BASELINE:
            raise ConflictError(
                f"Baseline in status '{status}' cannot be cancelled",
                code="invalid_baseline_state",
            )
        return
    if status not in DECISIONABLE_BASELINE:
        raise ConflictError(
            f"Only a submitted baseline can be reviewed (current status: {status})",
            code="invalid_baseline_state",
        )
    if decision == "approved":
        latest = (
            RequirementAnalysis.query.filter_by(
                organization_id=info["obj"].organization_id,
                baseline_id=info["obj"].id,
                baseline_version_number=info["version"],
                status="completed",
            )
            .order_by(RequirementAnalysis.created_at.desc())
            .first()
        )
        if latest is not None:
            blocking = RequirementFinding.query.filter_by(
                analysis_id=latest.id, status="open", blocking=True
            ).count()
            if blocking:
                raise ConflictError(
                    f"Baseline has {blocking} unresolved blocking finding(s)",
                    code="blocking_requirement_findings",
                    details={"analysis_id": str(latest.id), "blocking_count": blocking},
                )


def decide(
    *,
    artifact_type: str,
    artifact_id,
    decision: str,
    org_id,
    decider_id: str,
    decider_roles,
    version=None,
    content_hash: str | None = None,
    reason: str | None = None,
    expires_at=None,
):
    """Validate and record an immutable approval bound to the current version + hash."""
    if decision not in DECISIONS:
        raise ValidationError(f"Unknown decision '{decision}'")
    reason = (reason or "").strip() or None

    info = resolve_artifact(artifact_type, artifact_id, org_id)
    _check_binding(info, version, content_hash)
    _check_state_machine(info, decision)

    if (
        decision == "cancelled"
        and info["author_id"] != decider_id
        and "approval" not in set(decider_roles or [])
    ):
        raise AuthorizationError("Only the artifact author or an approval reviewer may cancel it")

    if decision in SELF_APPROVAL_FORBIDDEN and info["author_id"] == decider_id:
        raise ConflictError(
            "Segregation of duties: the author of an artifact cannot approve or waive it",
            code="segregation_of_duties",
        )

    if decision == "waived":
        if not reason:
            raise ValidationError("A waive requires a recorded reason")
        if expires_at is None:
            raise ValidationError("A waive requires an expiry")

    approval = Approval(
        id=new_uuid(),
        organization_id=org_id,
        project_id=info["project_id"],
        artifact_type=info["type"],
        artifact_id=info["id"],
        artifact_version=info["version"],
        artifact_hash=info["content_hash"],
        decision=decision,
        reason=reason,
        decider_id=decider_id,
        decider_roles=sorted(decider_roles or []),
        author_id=info["author_id"],
        expires_at=expires_at,
        created_at=utcnow(),
    )
    db.session.add(approval)

    if info["type"] == "requirement_baseline":
        info["obj"].status = BASELINE_TRANSITIONS[decision]
    elif info["type"] in SUPPORTED_VERSIONED_ARTIFACTS:
        info["obj"].status = BASELINE_TRANSITIONS[decision]

    db.session.commit()
    return approval, info


def has_decision(artifact_type: str, artifact_id, version: int, decision: str) -> Approval | None:
    return (
        Approval.query.filter_by(
            artifact_type=artifact_type,
            artifact_id=str(artifact_id),
            artifact_version=version,
            decision=decision,
        )
        .order_by(Approval.created_at.desc())
        .first()
    )


def serialize(approval: Approval) -> dict:
    return {
        "id": str(approval.id),
        "artifact_type": approval.artifact_type,
        "artifact_id": approval.artifact_id,
        "artifact_version": approval.artifact_version,
        "artifact_hash": approval.artifact_hash,
        "decision": approval.decision,
        "reason": approval.reason,
        "decider_id": approval.decider_id,
        "author_id": approval.author_id,
        "self_approval": bool(approval.author_id and approval.decider_id == approval.author_id),
        "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
        "created_at": approval.created_at.isoformat(),
    }
