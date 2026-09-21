import hashlib
import json
from datetime import datetime

from flask import Blueprint, g, request

from ..api.responses import ok
from ..audit.service import record_audit, verify_chain
from ..auth.decorators import require_scope
from ..auth.roles import has_scope
from ..errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from ..extensions import db
from ..models import (
    AcceptanceSession,
    AgentRun,
    Approval,
    Artifact,
    ChangeSet,
    Deployment,
    DeploymentPlan,
    Project,
    ProjectGate,
    ProjectGateDecision,
    ProjectGateEvidence,
    ProjectGateHistory,
    ProjectResponsibilityAssignment,
    Release,
    ReleaseReadinessCheck,
    RepositoryConnection,
    RequirementBaseline,
    TraceLink,
    User,
    WorkItem,
)
from ..utils import new_uuid, utcnow

bp = Blueprint("gates", __name__, url_prefix="/projects")

GATE_CHECKS = {
    1: ("secure setup", ["project_exists", "repository_configured", "repository_connection_verified", "diagnostic_run_passed", "sandbox_readiness_passed", "audit_chain_verified"], ["organization_administrator"]),
    2: ("requirements", ["baseline_exists", "baseline_submitted", "baseline_current_version_hash_present", "blocking_findings_resolved_or_waived", "mandatory_work_items_present", "requirements_approval_recorded"], ["product_owner"]),
    3: ("architecture and plan", ["architecture_exists", "architecture_approved", "technical_plan_exists", "technical_plan_approved", "traceability_available", "security_controls_present"], ["architecture_reviewer"]),
    4: ("managed inference and change set", ["approved_plan_exists", "agent_run_completed", "checkpoint_evidence_available", "provider_output_schema_valid", "change_set_exists", "change_set_hash_present", "tests_bound_to_change_set_hash", "scans_bound_to_change_set_hash", "reproducibility_evidence_present", "provider_usage_or_cost_evidence_present_or_explicitly_not_available", "change_set_approval_recorded"], ["qa_reviewer"]),
    5: ("ui ux and acceptance", ["design_artifact_exists", "design_approval_recorded", "preview_exists", "preview_is_protected", "preview_is_unexpired", "acceptance_session_completed", "all_acceptance_criteria_passed_or_waived", "defects_resolved_or_explicitly_accepted", "automated_accessibility_baseline_passed"], ["product_owner", "designer", "qa_reviewer"]),
    6: ("release deployment and rollback", ["release_exists", "release_readiness_passed", "immutable_package_present", "sbom_present", "checksums_present", "image_digest_present", "deployment_plan_exists", "deployment_plan_approved", "deployment_succeeded", "health_checks_passed", "rollback_exercise_succeeded"], ["release_manager", "security_approver"]),
    7: ("security and operations readiness", ["security_baseline_passed", "dependency_and_secret_scans_passed", "production_scale_load_evidence_present", "checkpoint_recovery_evidence_present", "backup_restore_evidence_present", "rpo_rto_evidence_present", "prometheus_scrape_valid", "alert_rules_valid", "alert_delivery_test_passed", "retention_policy_configured", "retention_dry_run_recorded", "retention_execution_recorded", "operations_readiness_approval_recorded"], ["security_approver", "operations_approver"]),
}
EVIDENCE_STATUSES = {"not_run", "passed", "failed", "waived", "not_applicable", "blocked"}
PASSING_STATUSES = {"passed", "waived", "not_applicable"}
DECISIONS = {"approved", "rejected", "changes_requested", "waived"}
APPROVAL_MODES = {"human_api", "api_automation", "disabled"}
GATE_POLICY_DEFAULTS = {
    "approval_mode": "human_api",
    "require_gate_decisions": True,
    "require_project_responsibility_assignment": True,
    "allow_waivers": True,
    "require_previous_gate_closed": True,
    "auto_sync_evidence": True,
}
ROLE_FOR_RESPONSIBILITY = {
    "product_owner": "product_owner",
    "architecture_reviewer": "architect",
    "qa_reviewer": "qa_engineer",
    "designer": "designer",
    "release_manager": "release_manager",
    "security_approver": "security_approver",
    "operations_approver": "operations_approver",
}


@bp.get("/<uuid:project_id>/gate-policy")
@require_scope("config:read")
def get_project_gate_policy(project_id):
    return ok(_policy(_project(project_id)))


@bp.patch("/<uuid:project_id>/gate-policy")
@require_scope("config:manage")
def update_project_gate_policy(project_id):
    project = _project(project_id)
    updates = _validate_policy_payload(request.get_json(silent=True) or {})
    settings = dict(project.settings or {})
    policy = _policy(project)
    policy.update(updates)
    policy["version"] = _next_policy_version(policy.get("version"))
    settings["gate_policy"] = policy
    project.settings = settings
    db.session.commit()
    _audit_project("project.gate_policy_updated", project, {"changes": sorted(updates), "version": policy["version"]})
    return ok(policy)


@bp.get("/<uuid:project_id>/gates")
@require_scope("project:read")
def list_gates(project_id):
    return ok([_serialize_gate(gate) for gate in _ensure_gates(_project(project_id))])


@bp.get("/<uuid:project_id>/gates/summary")
@require_scope("project:read")
def gate_summary(project_id):
    project = _project(project_id)
    gates = _ensure_gates(project)
    blocking = []
    for gate in gates:
        for key in _blocking_checks(gate):
            item = _evidence_map(gate).get(key)
            blocking.append({"gate": gate.number, "key": key, "status": item.status if item else "blocked"})
    policy = _policy(project)
    return ok(
        {
            "project_id": str(project.id),
            "overall_status": "closed" if all(gate.status == "closed" for gate in gates) else "blocked",
            "closed_gates": [gate.number for gate in gates if gate.status == "closed"],
            "open_gates": [gate.number for gate in gates if gate.status != "closed"],
            "blocking_checks": blocking,
            "approval_mode": policy["approval_mode"],
            "audit_chain_verified": verify_chain(project.organization_id)["verified"],
        }
    )


@bp.get("/<uuid:project_id>/gates/<int:gate_number>")
@require_scope("project:read")
def get_gate(project_id, gate_number):
    return ok(_serialize_gate(_gate(_project(project_id), gate_number)))


@bp.post("/<uuid:project_id>/gates/<int:gate_number>/sync")
@require_scope("config:manage")
def sync_gate(project_id, gate_number):
    project = _project(project_id)
    gate = _gate(project, gate_number)
    synced = []
    for key in gate.required_evidence:
        result = _derive_check(project, key)
        if result is None:
            continue
        item = _upsert_evidence(project, gate, key, result["status"], result.get("detail", ""), result.get("evidence", {}), source="botq.sync", producer_type="system", command=f"sync:{key}", diagnostics=result.get("diagnostics", {}))
        synced.append({"key": item.key, "status": item.status})
    _evaluate(gate, _policy(project))
    db.session.commit()
    _history(gate, "sync", {"synced": synced}, commit=True)
    _audit("gate.synced", gate, {"synced": synced})
    return ok(_serialize_gate(gate))


@bp.post("/<uuid:project_id>/gates/<int:gate_number>/evidence")
@require_scope("config:manage")
def submit_evidence(project_id, gate_number):
    project = _project(project_id)
    gate = _gate(project, gate_number)
    payload = request.get_json(silent=True) or {}
    key = _check_key(gate, payload.get("key"))
    status = _status(payload.get("status"))
    policy = _policy(project)
    if status == "waived":
        _require_waiver(policy, payload)
    evidence = payload.get("evidence") or {}
    if not isinstance(evidence, dict):
        raise ValidationError("evidence must be an object")
    idempotency_key = _idempotency_key(payload)
    if _idempotent_evidence(gate, idempotency_key):
        return ok(_serialize_gate(gate), status=200)
    item = _upsert_evidence(
        project,
        gate,
        key,
        status,
        str(payload.get("detail") or payload.get("reason") or ""),
        evidence,
        source=str(payload.get("source") or evidence.get("source") or "api"),
        producer_type=str(payload.get("producer_type") or "api"),
        command=payload.get("command"),
        executed_at=_parse_datetime(payload.get("executed_at"), "executed_at", default=utcnow()),
        expires_at=_parse_optional_datetime(payload.get("expires_at"), "expires_at"),
        diagnostics=payload.get("diagnostics") or {},
        content_hash=payload.get("content_hash"),
        idempotency_key=idempotency_key,
    )
    gate.status = "open"
    db.session.commit()
    _history(gate, "evidence", {"key": key, "status": status, "content_hash": item.content_hash}, commit=True)
    _audit("gate.evidence_submitted", gate, {"key": key, "status": status, "content_hash": item.content_hash})
    return ok(_serialize_gate(gate), status=201)


@bp.post("/<uuid:project_id>/gates/<int:gate_number>/evaluate")
@require_scope("project:read")
def evaluate_gate(project_id, gate_number):
    project = _project(project_id)
    gate = _gate(project, gate_number)
    if _policy(project)["auto_sync_evidence"]:
        for key in gate.required_evidence:
            if key not in _evidence_map(gate):
                result = _derive_check(project, key)
                if result is not None:
                    _upsert_evidence(project, gate, key, result["status"], result.get("detail", ""), result.get("evidence", {}), source="botq.sync", producer_type="system", command=f"sync:{key}")
    _evaluate(gate, _policy(project))
    db.session.commit()
    _history(gate, "evaluate", {"status": gate.status, "blocking": _blocking_checks(gate)}, commit=True)
    _audit("gate.evaluated", gate, {"blocking": _blocking_checks(gate), "status": gate.status})
    return ok(_serialize_gate(gate))


@bp.post("/<uuid:project_id>/gates/<int:gate_number>/decisions")
def decide_gate(project_id, gate_number):
    project = _project(project_id)
    return _record_decision(project, _gate(project, gate_number), request.get_json(silent=True) or {}, automated=False)


@bp.post("/<uuid:project_id>/gates/<int:gate_number>/auto-approve")
@require_scope("gate:approve")
def auto_approve_gate(project_id, gate_number):
    project = _project(project_id)
    gate = _gate(project, gate_number)
    policy = _policy(project)
    if policy["approval_mode"] != "api_automation":
        raise ConflictError("auto-approve requires api_automation approval mode", code="approval_mode_mismatch")
    if not _is_automation_user(g.user):
        raise AuthorizationError("auto-approve requires an active automation principal")
    payload = request.get_json(silent=True) or {}
    responsibilities = payload.get("responsibility_types") or GATE_CHECKS[gate.number][2]
    if not isinstance(responsibilities, list):
        raise ValidationError("responsibility_types must be a list")
    decisions = []
    base_key = _idempotency_key(payload) or new_uuid().hex
    for responsibility in responsibilities:
        response = _record_decision(
            project,
            gate,
            {**payload, "responsibility_type": responsibility, "decision": "approved", "comment": payload.get("comment") or "API automation approval", "idempotency_key": f"{base_key}:{responsibility}"},
            automated=True,
        )
        decisions.append(response[0].get_json()["data"])
    return ok({"gate": _serialize_gate(gate), "decisions": decisions}, status=201)


@bp.post("/<uuid:project_id>/gates/<int:gate_number>/close")
@require_scope("gate:close")
def close_gate(project_id, gate_number):
    project = _project(project_id)
    gate = _gate(project, gate_number)
    policy = _policy(project)
    _evaluate(gate, policy)
    blocking = _blocking_checks(gate)
    missing = _missing_decisions(gate, policy)
    dependency = _previous_gate_dependency(project, gate, policy)
    if blocking or missing or dependency:
        raise ConflictError("Gate is not ready to close", code="gate_not_ready", details={"blocking_checks": blocking, "blocking_evidence": blocking, "missing_decisions": missing, "dependency": dependency})
    gate.status = "closed"
    gate.closed_at = utcnow()
    gate.closed_by = g.user.id
    db.session.commit()
    _history(gate, "close", {"gate_number": gate.number}, commit=True)
    _audit("gate.closed", gate, {"gate_number": gate.number})
    return ok(_serialize_gate(gate))


@bp.post("/<uuid:project_id>/gates/<int:gate_number>/reopen")
@require_scope("gate:close")
def reopen_gate(project_id, gate_number):
    gate = _gate(_project(project_id), gate_number)
    payload = request.get_json(silent=True) or {}
    reason = str(payload.get("reason") or "").strip()
    if gate.status != "closed":
        raise ConflictError("Only a closed gate can be reopened")
    if not reason:
        raise ValidationError("reason is required")
    gate.status = "open"
    gate.closed_at = None
    gate.closed_by = None
    gate.reopened_at = utcnow()
    gate.reopened_by = g.user.id
    gate.reopen_reason = reason
    db.session.commit()
    _history(gate, "reopen", {"reason": reason}, commit=True)
    _audit("gate.reopened", gate, {"gate_number": gate.number, "reason": reason})
    return ok(_serialize_gate(gate))


@bp.get("/<uuid:project_id>/gates/<int:gate_number>/history")
@require_scope("project:read")
def gate_history(project_id, gate_number):
    return ok([_serialize_history(item) for item in _gate(_project(project_id), gate_number).history])


def _project(project_id):
    project = Project.query.filter_by(id=project_id, organization_id=g.organization.id).first()
    if project is None:
        raise NotFoundError("Project not found")
    return project


def _ensure_gates(project):
    existing = {gate.number: gate for gate in ProjectGate.query.filter_by(project_id=project.id).all()}
    for number, (name, required, _) in GATE_CHECKS.items():
        if number not in existing:
            existing[number] = ProjectGate(id=new_uuid(), organization_id=project.organization_id, project_id=project.id, number=number, name=name, required_evidence=required)
            db.session.add(existing[number])
        else:
            existing[number].name = name
            existing[number].required_evidence = required
    db.session.commit()
    return [existing[number] for number in sorted(existing)]


def _gate(project, gate_number):
    if gate_number not in GATE_CHECKS:
        raise ValidationError("gate_number must be between 1 and 7")
    _ensure_gates(project)
    return ProjectGate.query.filter_by(project_id=project.id, number=gate_number).first()


def _policy(project):
    org_policy = {**GATE_POLICY_DEFAULTS, **((project.organization.settings or {}).get("gate_policy") or {})}
    policy = {**org_policy, **((project.settings or {}).get("gate_policy") or {})}
    policy.setdefault("version", "gate-policy-v1")
    return policy


def _validate_policy_payload(payload):
    if not isinstance(payload, dict):
        raise ValidationError("gate policy must be an object")
    unknown = sorted(set(payload) - set(GATE_POLICY_DEFAULTS) - {"version"})
    if unknown:
        raise ValidationError(f"Unsupported gate policy field(s): {', '.join(unknown)}")
    updates = {}
    for key, value in payload.items():
        if key == "version":
            continue
        if key == "approval_mode":
            mode = str(value or "").strip().lower()
            if mode not in APPROVAL_MODES:
                raise ValidationError("approval_mode must be human_api, api_automation, or disabled")
            updates[key] = mode
        else:
            if not isinstance(value, bool):
                raise ValidationError(f"{key} must be boolean")
            updates[key] = value
    return updates


def _next_policy_version(current):
    try:
        number = int(str(current or "gate-policy-v1").rsplit("v", 1)[1])
    except ValueError:
        number = 1
    return f"gate-policy-v{number + 1}"


def _check_key(gate, value):
    key = str(value or "").strip().lower()
    if key not in gate.required_evidence:
        raise ValidationError("key is not a configured check for this gate")
    return key


def _status(value):
    status = str(value or "").strip().lower()
    if status not in EVIDENCE_STATUSES:
        raise ValidationError("status must be not_run, passed, failed, waived, not_applicable, or blocked")
    return status


def _require_waiver(policy, payload):
    if not policy["allow_waivers"]:
        raise ConflictError("Gate waivers are disabled by policy", code="waivers_disabled")
    if not str(payload.get("detail") or payload.get("reason") or "").strip():
        raise ValidationError("waived evidence requires reason/detail")
    if not payload.get("expires_at"):
        raise ValidationError("waived evidence requires expires_at")


def _idempotency_key(payload):
    value = request.headers.get("Idempotency-Key") or payload.get("idempotency_key")
    if value is None:
        return None
    value = str(value).strip()
    if not value or len(value) > 128:
        raise ValidationError("idempotency_key must be 1-128 characters")
    return value


def _idempotent_evidence(gate, key):
    return ProjectGateEvidence.query.filter_by(gate_id=gate.id, idempotency_key=key).first() if key else None


def _idempotent_decision(gate, responsibility, key):
    return ProjectGateDecision.query.filter_by(gate_id=gate.id, responsibility_type=responsibility, idempotency_key=key).first() if key else None


def _upsert_evidence(project, gate, key, status, detail, evidence, *, source, producer_type, command=None, executed_at=None, expires_at=None, diagnostics=None, content_hash=None, idempotency_key=None):
    if diagnostics is not None and not isinstance(diagnostics, dict):
        raise ValidationError("diagnostics must be an object")
    item = ProjectGateEvidence.query.filter_by(gate_id=gate.id, key=key).first()
    if item is None:
        item = ProjectGateEvidence(id=new_uuid(), organization_id=project.organization_id, project_id=project.id, gate_id=gate.id, key=key, created_by=g.user.id)
        db.session.add(item)
    item.status = status
    item.detail = detail or ""
    item.evidence = evidence
    item.source = source
    item.producer_type = producer_type
    item.command = str(command) if command else None
    item.executed_at = executed_at or utcnow()
    item.expires_at = expires_at
    item.diagnostics = diagnostics or {}
    item.content_hash = content_hash or _hash_json({"key": key, "status": status, "evidence": evidence})
    item.idempotency_key = idempotency_key or item.idempotency_key
    return item


def _record_decision(project, gate, payload, automated):
    if not has_scope(g.user, "approval") and not has_scope(g.user, "gate:approve"):
        raise AuthorizationError("approval scope required")
    if not g.user.is_active:
        raise AuthorizationError("inactive users cannot approve gates")
    policy = _policy(project)
    responsibility = str(payload.get("responsibility_type") or "").strip().lower()
    decision = str(payload.get("decision") or "").strip().lower()
    if responsibility not in GATE_CHECKS[gate.number][2]:
        raise ValidationError("responsibility_type is not valid for this gate")
    if decision not in DECISIONS:
        raise ValidationError("decision must be approved, rejected, changes_requested, or waived")
    if decision == "waived":
        _require_waiver(policy, payload)
    if policy["approval_mode"] == "disabled":
        raise ConflictError("Gate decisions are disabled by policy", code="gate_decisions_disabled")
    if automated or policy["approval_mode"] == "api_automation":
        if policy["approval_mode"] != "api_automation" or not _is_automation_user(g.user):
            raise AuthorizationError("automation decision requires api_automation mode and automation principal")
    elif policy["approval_mode"] == "human_api" and _is_automation_user(g.user):
        raise AuthorizationError("human_api policy requires a human user")
    _require_role(responsibility)
    _require_assigned_reviewer(project, responsibility, policy)
    idempotency_key = _idempotency_key(payload)
    existing = _idempotent_decision(gate, responsibility, idempotency_key)
    if existing:
        return ok(_serialize_decision(existing))
    evidence = list(gate.evidence)
    item = ProjectGateDecision(
        id=new_uuid(),
        organization_id=project.organization_id,
        project_id=project.id,
        gate_id=gate.id,
        responsibility_type=responsibility,
        decision=decision,
        comment=str(payload.get("comment") or payload.get("reason") or "").strip() or None,
        decided_by=g.user.id,
        decider_type="automation" if _is_automation_user(g.user) else "human",
        approval_mode=policy["approval_mode"],
        evidence_refs=[{"key": ev.key, "id": str(ev.id)} for ev in evidence],
        evidence_hashes=[ev.content_hash for ev in evidence if ev.content_hash],
        policy_version=policy["version"],
        idempotency_key=idempotency_key,
    )
    db.session.add(item)
    if decision != "approved":
        gate.status = "open"
    db.session.commit()
    _history(gate, "decision", {"responsibility_type": responsibility, "decision": decision}, commit=True)
    _audit("gate.decision_recorded", gate, {"responsibility_type": responsibility, "decision": decision})
    return ok(_serialize_decision(item), status=201)


def _require_role(responsibility):
    if _is_automation_user(g.user) and any(
        role.name == "gate_automation" for role in g.user.roles
    ):
        return
    if responsibility == "organization_administrator":
        if any(role.name == "organization_administrator" for role in g.user.roles):
            return
        raise AuthorizationError("organization_administrator role required")
    if any(role.name == "organization_administrator" for role in g.user.roles):
        return
    role = ROLE_FOR_RESPONSIBILITY.get(responsibility)
    if not role or not any(item.name == role for item in g.user.roles):
        raise AuthorizationError("The current user does not have the organization role for this decision")


def _require_assigned_reviewer(project, responsibility, policy):
    if not policy["require_project_responsibility_assignment"] or responsibility == "organization_administrator":
        return
    now = utcnow()
    assignment = ProjectResponsibilityAssignment.query.filter(
        ProjectResponsibilityAssignment.project_id == project.id,
        ProjectResponsibilityAssignment.user_id == g.user.id,
        ProjectResponsibilityAssignment.responsibility_type == responsibility,
        ProjectResponsibilityAssignment.is_primary.is_(True),
        ProjectResponsibilityAssignment.effective_from <= now,
        (ProjectResponsibilityAssignment.effective_until.is_(None)) | (ProjectResponsibilityAssignment.effective_until > now),
    ).first()
    if assignment is None:
        raise AuthorizationError(f"Current user is not the active primary {responsibility} for this project")


def _evaluate(gate, policy):
    blocking = _blocking_checks(gate)
    missing = _missing_decisions(gate, policy)
    dependency = _previous_gate_dependency(gate.project, gate, policy)
    gate.status = "ready" if not blocking and not missing and not dependency else "open"
    gate.evaluated_at = utcnow()


def _evidence_map(gate):
    return {item.key: item for item in gate.evidence}


def _blocking_checks(gate):
    evidence = _evidence_map(gate)
    now = utcnow()
    blocked = []
    for key in gate.required_evidence:
        item = evidence.get(key)
        if item is None or item.status not in PASSING_STATUSES or (item.expires_at and item.expires_at <= now):
            blocked.append(key)
    return blocked


def _missing_decisions(gate, policy):
    if not policy["require_gate_decisions"] or policy["approval_mode"] == "disabled":
        return []
    required = set(GATE_CHECKS[gate.number][2])
    approved = {item.responsibility_type for item in gate.decisions if item.decision == "approved"}
    return sorted(required - approved)


def _previous_gate_dependency(project, gate, policy):
    if not policy["require_previous_gate_closed"] or gate.number == 1:
        return None
    previous = ProjectGate.query.filter_by(project_id=project.id, number=gate.number - 1).first()
    return None if previous and previous.status == "closed" else {"gate": gate.number - 1, "status": previous.status if previous else "missing"}


def _derive_check(project, key):
    if key == "project_exists":
        return _passed({"project_id": str(project.id)})
    if key == "repository_configured":
        return _passed() if RepositoryConnection.query.filter_by(project_id=project.id).first() else None
    if key == "repository_connection_verified":
        repo = RepositoryConnection.query.filter_by(project_id=project.id).first()
        return _passed({"repository_status": repo.status}) if repo and repo.status == "verified" else None
    if key == "audit_chain_verified":
        result = verify_chain(project.organization_id)
        return _passed(result) if result["verified"] else {"status": "failed", "detail": result.get("failure") or "", "evidence": result}
    if key == "baseline_exists":
        return _passed() if RequirementBaseline.query.filter_by(project_id=project.id).first() else None
    if key == "baseline_submitted":
        return _passed() if RequirementBaseline.query.filter(RequirementBaseline.project_id == project.id, RequirementBaseline.status.in_(["submitted", "approved"])).first() else None
    if key == "baseline_current_version_hash_present":
        baseline = RequirementBaseline.query.filter_by(project_id=project.id).first()
        version = baseline.versions[-1] if baseline and baseline.versions else None
        return _passed({"content_hash": version.content_hash}) if version and version.content_hash else None
    if key == "mandatory_work_items_present":
        return _passed() if WorkItem.query.filter_by(project_id=project.id).first() else None
    if key == "requirements_approval_recorded":
        return _approval_check(project, "requirement_baseline")
    if key == "architecture_exists":
        return _artifact_check(project, "architecture")
    if key == "architecture_approved":
        return _approval_check(project, "architecture")
    if key == "technical_plan_exists":
        return _artifact_check(project, "technical_plan")
    if key in {"technical_plan_approved", "approved_plan_exists"}:
        return _approval_check(project, "technical_plan")
    if key == "traceability_available":
        return _passed() if TraceLink.query.filter_by(project_id=project.id).first() else None
    if key == "agent_run_completed":
        return _passed() if AgentRun.query.filter_by(project_id=project.id, status="completed").first() else None
    if key == "checkpoint_evidence_available":
        run = AgentRun.query.filter_by(project_id=project.id).first()
        return _passed() if run and any(cp.evidence for cp in run.checkpoints) else None
    if key == "change_set_exists":
        return _passed() if ChangeSet.query.filter_by(project_id=project.id).first() else None
    if key == "change_set_hash_present":
        return _passed() if ChangeSet.query.filter(ChangeSet.project_id == project.id, ChangeSet.diff_hash.is_not(None)).first() else None
    if key == "change_set_approval_recorded":
        return _approval_check(project, "change_set")
    if key == "design_artifact_exists":
        return _artifact_check(project, "design_mockup") or _artifact_check(project, "design")
    if key == "design_approval_recorded":
        return _approval_check(project, "design_mockup") or _approval_check(project, "design")
    if key == "preview_exists":
        return _passed() if _project_preview(project) else None
    if key == "preview_is_protected":
        preview = _project_preview(project)
        return _passed() if preview and preview.access_policy.get("authentication") == "required" else None
    if key == "preview_is_unexpired":
        preview = _project_preview(project)
        return _passed() if preview and preview.expires_at > utcnow() else None
    if key == "acceptance_session_completed":
        return _passed() if AcceptanceSession.query.filter_by(project_id=project.id, status="completed").first() else None
    if key == "release_exists":
        return _passed() if Release.query.filter_by(project_id=project.id).first() else None
    if key == "release_readiness_passed":
        return _passed() if ReleaseReadinessCheck.query.filter_by(project_id=project.id, status="passed").first() else None
    if key == "deployment_plan_exists":
        return _passed() if DeploymentPlan.query.filter_by(project_id=project.id).first() else None
    if key == "deployment_plan_approved":
        return _approval_check(project, "deployment_plan")
    if key == "deployment_succeeded":
        return _passed() if Deployment.query.filter_by(project_id=project.id, status="succeeded").first() else None
    return None


def _passed(evidence=None):
    return {"status": "passed", "detail": "synchronized from botq records", "evidence": evidence or {}}


def _artifact_check(project, artifact_type):
    return _passed() if Artifact.query.filter_by(project_id=project.id, artifact_type=artifact_type).first() else None


def _approval_check(project, artifact_type):
    return _passed() if Approval.query.filter_by(project_id=project.id, artifact_type=artifact_type, decision="approved").first() else None


def _project_preview(project):
    from ..models import PreviewDeployment

    return PreviewDeployment.query.filter_by(project_id=project.id, status="active").first()


def _serialize_gate(gate):
    policy = _policy(gate.project)
    return {
        "id": str(gate.id),
        "project_id": str(gate.project_id),
        "number": gate.number,
        "name": gate.name,
        "status": gate.status,
        "required_evidence": gate.required_evidence,
        "checks": [_serialize_evidence_item(gate, key) for key in gate.required_evidence],
        "blocking_checks": _blocking_checks(gate),
        "blocking_evidence": _blocking_checks(gate),
        "missing_decisions": _missing_decisions(gate, policy),
        "evidence": [_serialize_evidence(item) for item in gate.evidence],
        "decisions": [_serialize_decision(item) for item in gate.decisions],
        "policy": {"approval_mode": policy["approval_mode"], "version": policy["version"]},
        "evaluated_at": gate.evaluated_at.isoformat() if gate.evaluated_at else None,
        "closed_at": gate.closed_at.isoformat() if gate.closed_at else None,
        "closed_by": str(gate.closed_by) if gate.closed_by else None,
        "reopened_at": gate.reopened_at.isoformat() if gate.reopened_at else None,
        "reopened_by": str(gate.reopened_by) if gate.reopened_by else None,
        "reopen_reason": gate.reopen_reason,
    }


def _serialize_evidence_item(gate, key):
    item = _evidence_map(gate).get(key)
    return {"key": key, "status": "blocked", "detail": "missing evidence"} if item is None else _serialize_evidence(item)


def _serialize_evidence(item):
    return {
        "id": str(item.id),
        "key": item.key,
        "status": item.status,
        "detail": item.detail,
        "evidence": item.evidence,
        "source": item.source,
        "content_hash": item.content_hash,
        "producer_type": item.producer_type,
        "command": item.command,
        "executed_at": item.executed_at.isoformat() if item.executed_at else None,
        "expires_at": item.expires_at.isoformat() if item.expires_at else None,
        "diagnostics": item.diagnostics,
        "created_by": str(item.created_by),
        "created_at": item.created_at.isoformat(),
    }


def _serialize_decision(item):
    return {
        "id": str(item.id),
        "responsibility_type": item.responsibility_type,
        "decision": item.decision,
        "comment": item.comment,
        "decider_id": str(item.decided_by),
        "decider_type": item.decider_type,
        "approval_mode": item.approval_mode,
        "evidence_references": item.evidence_refs,
        "evidence_hashes": item.evidence_hashes,
        "policy_version": item.policy_version,
        "created_at": item.created_at.isoformat(),
    }


def _serialize_history(item):
    return {"id": str(item.id), "action": item.action, "actor_id": str(item.actor_id) if item.actor_id else None, "actor_type": item.actor_type, "details": item.details, "created_at": item.created_at.isoformat()}


def _history(gate, action, details, commit=False):
    entry = ProjectGateHistory(id=new_uuid(), organization_id=gate.organization_id, project_id=gate.project_id, gate_id=gate.id, action=action, actor_id=g.user.id if getattr(g, "user", None) else None, actor_type="automation" if getattr(g, "user", None) and _is_automation_user(g.user) else "user", details=details, idempotency_key=request.headers.get("Idempotency-Key"))
    db.session.add(entry)
    if commit:
        db.session.commit()
    return entry


def _audit(action, gate, metadata):
    record_audit(action=action, actor_id=str(g.user.id), target_type="project_gate", target_id=gate.id, organization_id=gate.organization_id, metadata={"project_id": str(gate.project_id), "gate_number": gate.number, **metadata})


def _audit_project(action, project, metadata):
    record_audit(action=action, actor_id=str(g.user.id), target_type="project", target_id=project.id, organization_id=project.organization_id, metadata=metadata)


def _hash_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _parse_datetime(value, field, default=None):
    if not value:
        return default
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{field} must be an ISO-8601 datetime") from exc
    return parsed.replace(tzinfo=None)


def _parse_optional_datetime(value, field):
    return _parse_datetime(value, field) if value else None


def _is_automation_user(user: User):
    return bool(user and user.is_active and user.external_provider == "automation")
