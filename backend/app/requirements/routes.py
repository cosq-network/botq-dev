import uuid

from flask import Blueprint, current_app, g, request

from ..api.responses import ok
from ..audit.service import record_audit
from ..errors import AuthenticationError, ConflictError, NotFoundError, ValidationError
from ..extensions import db
from ..models import (
    Artifact,
    Project,
    RequirementAnalysis,
    RequirementBaseline,
    RequirementBaselineVersion,
    RequirementFinding,
    WorkItem,
)
from ..utils import new_uuid
from ..work_items import service as work_item_service
from . import analysis as analysis_service
from .analysis import fingerprint
from .service import content_hash, diff_contents, normalize_content, summarize_diff

bp = Blueprint("requirements", __name__, url_prefix="/requirements")

SUBMITTABLE_STATUSES = {"draft"}


def _parse_uuid(value, field: str):
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValidationError(f"{field} must be a valid UUID") from exc


def _serialize_baseline(baseline: RequirementBaseline, *, with_content: bool = False) -> dict:
    payload = {
        "id": str(baseline.id),
        "project_id": str(baseline.project_id),
        "title": baseline.title,
        "status": baseline.status,
        "current_version": baseline.current_version,
        "created_by": baseline.created_by,
        "created_at": baseline.created_at.isoformat(),
        "updated_at": baseline.updated_at.isoformat(),
        "version_count": len(baseline.versions),
    }
    if with_content:
        current = _current_version(baseline)
        payload["content"] = current.content
        payload["content_hash"] = current.content_hash
    return payload


def _serialize_finding(finding: RequirementFinding) -> dict:
    return {
        "id": str(finding.id),
        "analysis_id": str(finding.analysis_id),
        "category": finding.category,
        "severity": finding.severity,
        "blocking": finding.blocking,
        "status": finding.status,
        "title": finding.title,
        "description": finding.description,
        "evidence": finding.evidence,
        "resolution": finding.resolution,
        "resolved_by": finding.resolved_by,
        "resolved_at": finding.resolved_at.isoformat() if finding.resolved_at else None,
        "created_at": finding.created_at.isoformat(),
    }


def _serialize_analysis(analysis: RequirementAnalysis, *, include_findings: bool = True) -> dict:
    payload = {
        "id": str(analysis.id),
        "project_id": str(analysis.project_id),
        "baseline_id": str(analysis.baseline_id),
        "baseline_version": analysis.baseline_version_number,
        "baseline_hash": analysis.baseline_hash,
        "provider": analysis.provider,
        "prompt_version": analysis.prompt_version,
        "policy_version": analysis.policy_version,
        "status": analysis.status,
        "summary": analysis.summary,
        "proposed_work_items": analysis.proposed_work_items,
        "applied_work_item_count": len(analysis.work_items),
        "created_by": analysis.created_by,
        "created_at": analysis.created_at.isoformat(),
    }
    if include_findings:
        payload["findings"] = [_serialize_finding(finding) for finding in analysis.findings]
    return payload


def _serialize_version(version: RequirementBaselineVersion, *, with_content: bool = True) -> dict:
    payload = {
        "id": str(version.id),
        "baseline_id": str(version.baseline_id),
        "version": version.version,
        "content_hash": version.content_hash,
        "change_summary": version.change_summary,
        "created_by": version.created_by,
        "created_at": version.created_at.isoformat(),
    }
    if with_content:
        payload["content"] = version.content
    return payload


def _current_version(baseline: RequirementBaseline) -> RequirementBaselineVersion:
    for version in baseline.versions:
        if version.version == baseline.current_version:
            return version
    raise NotFoundError("Current baseline version not found")


@bp.post("/baselines")
def create_baseline():
    _require_write()
    org = _org()
    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or "").strip()
    if not title or len(title) > 200:
        raise ValidationError("title is required (max 200 characters)")
    project = _owned_project(payload.get("project_id"))
    if RequirementBaseline.query.filter_by(
        organization_id=org.id, project_id=project.id, title=title
    ).first():
        raise ConflictError(
            "A baseline with this title already exists for the project",
            code="duplicate_baseline_title",
        )

    content = normalize_content(payload.get("content"))
    baseline = RequirementBaseline(
        id=new_uuid(),
        organization_id=org.id,
        project_id=project.id,
        title=title,
        status="draft",
        current_version=1,
        created_by=str(g.user.id),
    )
    version = RequirementBaselineVersion(
        id=new_uuid(),
        organization_id=org.id,
        baseline_id=baseline.id,
        version=1,
        content=content,
        content_hash=content_hash(content),
        change_summary="initial version",
        created_by=str(g.user.id),
    )
    db.session.add_all([baseline, version])
    db.session.commit()
    record_audit(
        action="requirement_baseline.created",
        actor_id=str(g.user.id),
        target_type="requirement_baseline",
        target_id=baseline.id,
        organization_id=org.id,
        metadata={
            "project_id": str(project.id),
            "title": title,
            "content_hash": version.content_hash,
        },
    )
    return ok(_serialize_baseline(baseline, with_content=True), status=201)


@bp.get("/baselines")
def list_baselines():
    _require_read()
    org = _org()
    query = RequirementBaseline.query.filter_by(organization_id=org.id)
    project_id = request.args.get("project_id")
    if project_id:
        project = _owned_project(project_id)
        query = query.filter_by(project_id=project.id)
    status = request.args.get("status")
    if status:
        query = query.filter_by(status=status)
    baselines = query.order_by(RequirementBaseline.created_at.desc()).all()
    return ok([_serialize_baseline(b) for b in baselines])


@bp.get("/baselines/<uuid:baseline_id>")
def get_baseline(baseline_id):
    _require_read()
    baseline = _get_owned(baseline_id)
    return ok(_serialize_baseline(baseline, with_content=True))


@bp.get("/baselines/<uuid:baseline_id>/versions")
def list_versions(baseline_id):
    _require_read()
    baseline = _get_owned(baseline_id)
    return ok([_serialize_version(v, with_content=False) for v in baseline.versions])


@bp.get("/baselines/<uuid:baseline_id>/versions/<int:version>")
def get_version(baseline_id, version):
    _require_read()
    baseline = _get_owned(baseline_id)
    return ok(_serialize_version(_version_of(baseline, version)))


@bp.post("/baselines/<uuid:baseline_id>/versions")
def create_version(baseline_id):
    _require_write()
    org = _org()
    baseline = _get_owned(baseline_id)
    payload = request.get_json(silent=True) or {}
    content = normalize_content(payload.get("content"))
    digest = content_hash(content)
    current = _current_version(baseline)
    if digest == current.content_hash:
        raise ConflictError("The new content is identical to the current version", code="no_change")

    version_number = baseline.current_version + 1
    change_summary = (payload.get("change_summary") or "").strip() or None
    diff = diff_contents(current.content, content)
    if not change_summary:
        change_summary = summarize_diff(diff)[:500]

    version = RequirementBaselineVersion(
        id=new_uuid(),
        organization_id=org.id,
        baseline_id=baseline.id,
        version=version_number,
        content=content,
        content_hash=digest,
        change_summary=change_summary,
        created_by=str(g.user.id),
    )
    baseline.current_version = version_number
    if baseline.status != "draft":
        baseline.status = "draft"
    impacted_artifacts = (
        Artifact.query.filter_by(organization_id=org.id, source_baseline_id=baseline.id)
        .filter(Artifact.status.in_(["submitted", "approved"]))
        .all()
    )
    for artifact in impacted_artifacts:
        artifact.status = "changes_requested"
    db.session.add(version)
    db.session.commit()
    record_audit(
        action="requirement_baseline.version_created",
        actor_id=str(g.user.id),
        target_type="requirement_baseline",
        target_id=baseline.id,
        organization_id=org.id,
        metadata={
            "version": version_number,
            "content_hash": digest,
            "change_summary": change_summary,
            "material_change": diff["material"],
            "impacted_artifacts": [str(artifact.id) for artifact in impacted_artifacts],
        },
    )
    return ok(_serialize_baseline(baseline, with_content=True), status=201)


@bp.get("/baselines/<uuid:baseline_id>/versions/<int:version>/diff")
def diff_version(baseline_id, version):
    _require_read()
    baseline = _get_owned(baseline_id)
    source = _version_of(baseline, version)
    target_param = request.args.get("to")
    if target_param:
        try:
            target_number = int(target_param)
        except ValueError as exc:
            raise ValidationError("to must be an integer version number") from exc
    else:
        target_number = baseline.current_version
    target = _version_of(baseline, target_number)
    diff = diff_contents(source.content, target.content)
    return ok(
        {
            "from": source.version,
            "to": target.version,
            "from_hash": source.content_hash,
            "to_hash": target.content_hash,
            "diff": diff,
            "summary": summarize_diff(diff),
        }
    )


@bp.post("/baselines/<uuid:baseline_id>/submit")
def submit_baseline(baseline_id):
    _require_write()
    org = _org()
    baseline = _get_owned(baseline_id)
    if baseline.status not in SUBMITTABLE_STATUSES:
        raise ConflictError(
            f"Baseline in status '{baseline.status}' cannot be submitted",
            code="invalid_baseline_state",
        )
    version = _current_version(baseline)
    baseline.status = "submitted"
    db.session.commit()
    record_audit(
        action="requirement_baseline.submitted",
        actor_id=str(g.user.id),
        target_type="requirement_baseline",
        target_id=baseline.id,
        organization_id=org.id,
        metadata={"version": version.version, "content_hash": version.content_hash},
    )
    return ok(_serialize_baseline(baseline, with_content=True))


@bp.post("/baselines/<uuid:baseline_id>/analyze")
def analyze_baseline(baseline_id):
    """Run decomposition against exactly the current baseline version."""
    _require_write()
    org = _org()
    baseline = _get_owned(baseline_id)
    if baseline.status not in {"draft", "submitted"}:
        raise ConflictError(
            f"Baseline in status '{baseline.status}' cannot be analyzed",
            code="invalid_baseline_state",
        )
    version = _current_version(baseline)
    factory = current_app.config.get("REQUIREMENT_ANALYZER_FACTORY")
    analyzer = factory() if factory else analysis_service.configured_analyzer(current_app.config)
    result = analyzer.analyze(version.content)
    analysis_service.validate_result(result)
    provider = getattr(analyzer, "provider", "custom")
    prompt_version = current_app.config.get("REQUIREMENT_ANALYSIS_PROMPT_VERSION", "rules-v1")
    policy_version = current_app.config.get("REQUIREMENT_ANALYSIS_POLICY_VERSION", "baseline-v1")

    previous = RequirementAnalysis.query.filter_by(
        organization_id=org.id,
        baseline_id=baseline.id,
        baseline_version_number=version.version,
        status="completed",
    ).all()
    for prior in previous:
        prior.status = "superseded"

    analysis = RequirementAnalysis(
        id=new_uuid(),
        organization_id=org.id,
        project_id=baseline.project_id,
        baseline_id=baseline.id,
        baseline_version_id=version.id,
        baseline_version_number=version.version,
        baseline_hash=version.content_hash,
        provider=provider,
        prompt_version=prompt_version,
        policy_version=policy_version,
        status="completed",
        summary=analysis_service.summary(result.findings),
        proposed_work_items=result.proposed_work_items,
        created_by=str(g.user.id),
    )
    analysis.summary["work_item_proposal_count"] = len(result.proposed_work_items)
    db.session.add(analysis)
    for proposal in result.findings:
        db.session.add(
            RequirementFinding(
                id=new_uuid(),
                organization_id=org.id,
                project_id=baseline.project_id,
                analysis_id=analysis.id,
                category=proposal.category,
                severity=proposal.severity,
                blocking=proposal.blocking,
                status="open",
                fingerprint=fingerprint(proposal),
                title=proposal.title,
                description=proposal.description,
                evidence=proposal.evidence,
            )
        )
    db.session.commit()
    record_audit(
        action="requirement_analysis.created",
        actor_id=str(g.user.id),
        target_type="requirement_analysis",
        target_id=analysis.id,
        organization_id=org.id,
        metadata={
            "baseline_id": str(baseline.id),
            "baseline_version": version.version,
            "baseline_hash": version.content_hash,
            "provider": provider,
            "finding_count": len(result.findings),
            "blocking_count": sum(finding.blocking for finding in result.findings),
        },
    )
    return ok(_serialize_analysis(analysis), status=201)


@bp.get("/baselines/<uuid:baseline_id>/analyses")
def list_analyses(baseline_id):
    _require_read()
    baseline = _get_owned(baseline_id)
    analyses = (
        RequirementAnalysis.query.filter_by(organization_id=_org().id, baseline_id=baseline.id)
        .order_by(RequirementAnalysis.created_at.desc())
        .all()
    )
    return ok([_serialize_analysis(analysis, include_findings=False) for analysis in analyses])


@bp.get("/analyses/<uuid:analysis_id>")
def get_analysis(analysis_id):
    _require_read()
    return ok(_serialize_analysis(_get_owned_analysis(analysis_id)))


@bp.post("/analyses/<uuid:analysis_id>/findings/<uuid:finding_id>/resolve")
def resolve_finding(analysis_id, finding_id):
    _require_write()
    analysis = _get_owned_analysis(analysis_id)
    finding = RequirementFinding.query.filter_by(
        id=finding_id, organization_id=_org().id, analysis_id=analysis.id
    ).first()
    if finding is None:
        raise NotFoundError("Requirement finding not found")
    if finding.status != "open":
        raise ConflictError("Finding is already resolved", code="finding_already_resolved")
    payload = request.get_json(silent=True) or {}
    status = (payload.get("status") or "resolved").strip().lower()
    if status not in {"resolved", "waived"}:
        raise ValidationError("status must be resolved or waived")
    reason = (payload.get("reason") or "").strip()
    if status == "waived":
        from ..auth.roles import has_scope

        if not has_scope(g.user, "approval"):
            raise AuthenticationError("approval scope required to waive a finding")
        if not reason:
            raise ValidationError("A waived finding requires a reason")
    finding.status = status
    finding.resolution = reason or None
    finding.resolved_by = str(g.user.id)
    from ..utils import utcnow

    finding.resolved_at = utcnow()
    db.session.commit()
    record_audit(
        action="requirement_finding.resolved",
        actor_id=str(g.user.id),
        target_type="requirement_finding",
        target_id=finding.id,
        organization_id=_org().id,
        metadata={"analysis_id": str(analysis.id), "status": status},
    )
    return ok(_serialize_finding(finding))


@bp.post("/analyses/<uuid:analysis_id>/work-items")
def apply_work_items(analysis_id):
    _require_write()
    analysis = _get_owned_analysis(analysis_id)
    baseline = _get_owned(analysis.baseline_id)
    if baseline.current_version != analysis.baseline_version_number:
        raise ConflictError(
            "The baseline changed after this analysis; analyze the current version first",
            code="stale_analysis",
        )
    existing = (
        WorkItem.query.filter_by(source_analysis_id=analysis.id).order_by(WorkItem.number).all()
    )
    if existing:
        return ok([work_item_service.serialize(item) for item in existing])

    created_by = f"analysis:{analysis.id}"
    by_ref = {}
    for proposal in analysis.proposed_work_items:
        parent = by_ref.get(proposal.get("parent_ref"))
        kind = work_item_service.validate_enum(
            proposal.get("kind"), work_item_service.KINDS, "kind"
        )
        work_item_service.validate_parent(kind, parent)
        number = work_item_service.next_number(analysis.project_id)
        item = work_item_service.new_work_item(
            organization_id=_org().id,
            project_id=analysis.project_id,
            code=f"{baseline.project.key.upper()}-{number}",
            number=number,
            kind=kind,
            parent_id=parent.id if parent else None,
            title=(proposal.get("title") or "Generated work item")[:200],
            description=proposal.get("description"),
            acceptance_criteria=proposal.get("acceptance_criteria") or [],
            priority=proposal.get("priority") or "medium",
            risk=proposal.get("risk") or "medium",
            status="draft",
            source_baseline_id=baseline.id,
            source_analysis_id=analysis.id,
            source_refs=proposal.get("source_refs") or [],
            is_derived=False,
            created_by=created_by,
        )
        db.session.add(item)
        db.session.flush()
        by_ref[proposal["ref"]] = item
    db.session.commit()
    record_audit(
        action="requirement_analysis.work_items_applied",
        actor_id=str(g.user.id),
        target_type="requirement_analysis",
        target_id=analysis.id,
        organization_id=_org().id,
        metadata={"work_item_count": len(by_ref), "baseline_id": str(baseline.id)},
    )
    return ok([work_item_service.serialize(item) for item in by_ref.values()], status=201)


@bp.post("/baselines/<uuid:baseline_id>/approve")
def approve_baseline(baseline_id):
    return _review_decision(baseline_id, "approved")


@bp.post("/baselines/<uuid:baseline_id>/reject")
def reject_baseline(baseline_id):
    return _review_decision(baseline_id, "rejected")


@bp.post("/baselines/<uuid:baseline_id>/request-changes")
def request_changes_baseline(baseline_id):
    return _review_decision(baseline_id, "changes_requested")


@bp.post("/baselines/<uuid:baseline_id>/waive")
def waive_baseline(baseline_id):
    return _review_decision(baseline_id, "waived")


@bp.post("/baselines/<uuid:baseline_id>/cancel")
def cancel_baseline(baseline_id):
    return _review_decision(baseline_id, "cancelled")


def _review_decision(baseline_id, decision):
    from ..approvals.routes import _decide

    payload = request.get_json(silent=True) or {}
    _decide("requirement_baseline", baseline_id, decision, payload)
    baseline = _get_owned(baseline_id)
    return ok(_serialize_baseline(baseline, with_content=True))


def _version_of(baseline: RequirementBaseline, version_number: int) -> RequirementBaselineVersion:
    for version in baseline.versions:
        if version.version == version_number:
            return version
    raise NotFoundError(f"Baseline version {version_number} not found")


def _owned_project(project_id) -> Project:
    if not project_id:
        raise ValidationError("project_id is required")
    org = _org()
    project = Project.query.filter_by(
        id=_parse_uuid(project_id, "project_id"), organization_id=org.id
    ).first()
    if project is None:
        raise NotFoundError("Project not found")
    return project


def _get_owned(baseline_id) -> RequirementBaseline:
    org = _org()
    baseline = RequirementBaseline.query.filter_by(id=baseline_id, organization_id=org.id).first()
    if baseline is None:
        raise NotFoundError("Requirement baseline not found")
    return baseline


def _get_owned_analysis(analysis_id) -> RequirementAnalysis:
    analysis = RequirementAnalysis.query.filter_by(
        id=analysis_id, organization_id=_org().id
    ).first()
    if analysis is None:
        raise NotFoundError("Requirement analysis not found")
    return analysis


def _org():
    org = getattr(g, "organization", None)
    if org is None:
        raise AuthenticationError("Authenticated organization not found")
    return org


def _require_read() -> None:
    _require_scope("requirement:read")


def _require_write() -> None:
    _require_scope("requirement:write")


def _require_scope(scope: str) -> None:
    from ..auth.roles import has_scope

    user = getattr(g, "user", None)
    if user is None or not has_scope(user, scope):
        raise AuthenticationError(f"{scope} scope required")
