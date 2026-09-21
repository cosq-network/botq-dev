from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import Blueprint, current_app, g, request

from ..api.responses import ok
from ..approvals.routes import _decide
from ..artifacts import service
from ..audit.service import record_audit
from ..errors import AuthenticationError, ConflictError, NotFoundError, ValidationError
from ..extensions import db
from ..models import (
    AcceptanceResult,
    AcceptanceSession,
    Artifact,
    Defect,
    DesignComment,
    DesignLink,
    DesignReference,
    PreviewDeployment,
    TraceLink,
    WorkItem,
)
from ..utils import new_uuid, utcnow
from .adapter import PenpotAdapter
from .preview import WebhookPreviewDeploymentAdapter

bp = Blueprint("design", __name__, url_prefix="/design")

OUTCOMES = {"pass", "fail", "blocked", "na"}
DEFECT_SEVERITIES = {"critical", "high", "medium", "low"}
DEFECT_STATUSES = {"open", "in_progress", "fixed", "verified", "reopened", "closed"}


@bp.post("/mockups")
def create_mockup():
    _require("design:write")
    org = _org()
    payload = request.get_json(silent=True) or {}
    project_id = _uuid(payload.get("project_id"), "project_id")
    architecture_id = _uuid(payload.get("source_architecture_id"), "source_architecture_id")
    architecture = Artifact.query.filter_by(
        id=architecture_id,
        project_id=project_id,
        organization_id=org.id,
        artifact_type="architecture",
        status="approved",
    ).first()
    if architecture is None:
        raise ConflictError(
            "Mockups require an approved architecture", code="architecture_not_approved"
        )
    title = _title(payload.get("title"))
    provider = (payload.get("provider") or "penpot").strip().lower()
    if provider != "penpot":
        raise ValidationError("provider must be penpot")
    file_id = (payload.get("file_id") or "").strip()
    if not file_id:
        raise ValidationError("file_id is required")
    file_url = _url(payload.get("file_url"), "file_url", required=False)
    preview_url = _url(payload.get("preview_url"), "preview_url", required=False)
    content = payload.get("content") or {"pages": [], "nodes": []}
    if not isinstance(content, dict):
        raise ValidationError("content must be an object")

    adapter = PenpotAdapter(current_app.config)
    artifact, version = service.new_artifact(
        organization_id=org.id,
        project_id=project_id,
        artifact_type="mockup",
        title=title,
        content={**content, "provider": provider, "file_id": file_id},
        created_by=str(g.user.id),
    )
    artifact.source_artifact_id = architecture.id
    artifact.source_artifact_version = architecture.current_version
    artifact.source_artifact_hash = service.current_version(architecture).content_hash
    reference = DesignReference(
        id=new_uuid(),
        organization_id=org.id,
        project_id=project_id,
        artifact_id=artifact.id,
        provider=provider,
        file_id=file_id,
        file_url=file_url,
        preview_url=preview_url,
        provider_metadata=payload.get("provider_metadata") or {},
        capabilities=adapter.capabilities,
        handoff=adapter.handoff(file_id, file_url),
        created_by=str(g.user.id),
    )
    db.session.add_all([artifact, version, reference])
    db.session.add(
        TraceLink(
            id=new_uuid(),
            organization_id=org.id,
            project_id=project_id,
            source_type="architecture",
            source_id=str(architecture.id),
            target_type="mockup",
            target_id=str(artifact.id),
            relation="informs",
            created_by=str(g.user.id),
        )
    )
    db.session.commit()
    _audit("mockup.created", artifact, {"architecture_id": str(architecture.id)})
    return ok(_serialize_mockup(artifact, include_content=True), status=201)


@bp.get("/mockups")
def list_mockups():
    _require("design:read")
    query = Artifact.query.filter_by(organization_id=_org().id, artifact_type="mockup")
    if request.args.get("project_id"):
        query = query.filter_by(project_id=_uuid(request.args["project_id"], "project_id"))
    return ok(
        [_serialize_mockup(item) for item in query.order_by(Artifact.created_at.desc()).all()]
    )


@bp.get("/mockups/<uuid:artifact_id>")
def get_mockup(artifact_id):
    _require("design:read")
    return ok(_serialize_mockup(_get_mockup(artifact_id), include_content=True))


@bp.post("/mockups/<uuid:artifact_id>/versions")
def revise_mockup(artifact_id):
    _require("design:write")
    artifact = _get_mockup(artifact_id)
    if artifact.status == "cancelled":
        raise ConflictError("Cancelled mockups cannot be revised", code="invalid_artifact_state")
    payload = request.get_json(silent=True) or {}
    content = payload.get("content")
    if not isinstance(content, dict) or not content:
        raise ValidationError("content must be a non-empty object")
    current = service.current_version(artifact)
    digest = service.content_hash(content)
    if digest == current.content_hash:
        raise ConflictError("The new content is identical to the current version", code="no_change")
    version = service.new_artifact_version(
        artifact=artifact,
        content=content,
        created_by=str(g.user.id),
        change_summary=payload.get("change_summary") or "revised mockup",
    )
    artifact.current_version = version.version
    artifact.status = "draft"
    db.session.add(version)
    db.session.commit()
    _audit("mockup.version_created", artifact, {"version": version.version})
    return ok(_serialize_mockup(artifact, include_content=True), status=201)


@bp.post("/mockups/<uuid:artifact_id>/submit")
def submit_mockup(artifact_id):
    _require("design:write")
    artifact = _get_mockup(artifact_id)
    if artifact.status not in service.SUBMITTABLE_STATUSES:
        raise ConflictError("Mockup is not in a submittable state", code="invalid_artifact_state")
    if not artifact.comments or all(comment.status != "open" for comment in artifact.comments):
        artifact.status = "submitted"
        db.session.commit()
        _audit("mockup.submitted", artifact, {})
        return ok(_serialize_mockup(artifact, include_content=True))
    raise ConflictError(
        "Resolve open mockup comments before submission", code="open_design_comments"
    )


@bp.post("/mockups/<uuid:artifact_id>/approve")
def approve_mockup(artifact_id):
    _require("design:read")
    payload = request.get_json(silent=True) or {}
    _decide("mockup", artifact_id, "approved", payload)
    return ok(_serialize_mockup(_get_mockup(artifact_id), include_content=True))


@bp.post("/mockups/<uuid:artifact_id>/request-changes")
def request_changes_mockup(artifact_id):
    _require("design:read")
    payload = request.get_json(silent=True) or {}
    _decide("mockup", artifact_id, "changes_requested", payload)
    return ok(_serialize_mockup(_get_mockup(artifact_id), include_content=True))


@bp.post("/mockups/<uuid:artifact_id>/comments")
def add_mockup_comment(artifact_id):
    _require("design:write")
    artifact = _get_mockup(artifact_id)
    payload = request.get_json(silent=True) or {}
    body = (payload.get("body") or "").strip()
    anchor = payload.get("anchor")
    if not body or not isinstance(anchor, dict):
        raise ValidationError("body and an anchor object are required")
    version = int(payload.get("version", artifact.current_version))
    if version < 1 or version > artifact.current_version:
        raise ValidationError("version must reference an existing mockup version")
    comment = DesignComment(
        id=new_uuid(),
        organization_id=_org().id,
        project_id=artifact.project_id,
        artifact_id=artifact.id,
        artifact_version=version,
        anchor=anchor,
        body=body,
        created_by=str(g.user.id),
    )
    db.session.add(comment)
    db.session.commit()
    return ok(_serialize_comment(comment), status=201)


@bp.post("/mockups/<uuid:artifact_id>/comments/<uuid:comment_id>/resolve")
def resolve_mockup_comment(artifact_id, comment_id):
    _require("design:write")
    artifact = _get_mockup(artifact_id)
    comment = DesignComment.query.filter_by(
        id=comment_id, artifact_id=artifact.id, organization_id=_org().id
    ).first()
    if comment is None:
        raise NotFoundError("Design comment not found")
    comment.status = "resolved"
    comment.resolved_by = str(g.user.id)
    comment.resolved_at = utcnow()
    db.session.commit()
    return ok(_serialize_comment(comment))


@bp.post("/mockups/<uuid:artifact_id>/links")
def link_mockup_work_item(artifact_id):
    _require("design:write")
    artifact = _get_mockup(artifact_id)
    payload = request.get_json(silent=True) or {}
    work_item = WorkItem.query.filter_by(
        id=_uuid(payload.get("work_item_id"), "work_item_id"),
        project_id=artifact.project_id,
        organization_id=_org().id,
    ).first()
    if work_item is None:
        raise NotFoundError("Work item not found in the mockup project")
    reference = DesignReference.query.filter_by(artifact_id=artifact.id).first()
    if reference is None:
        raise NotFoundError("Design reference not found")
    page_id = _optional_text(payload.get("page_id"))
    node_id = _optional_text(payload.get("node_id"))
    if not page_id and not node_id:
        raise ValidationError("page_id or node_id is required")
    link = DesignLink(
        id=new_uuid(),
        organization_id=_org().id,
        project_id=artifact.project_id,
        design_reference_id=reference.id,
        work_item_id=work_item.id,
        page_id=page_id,
        node_id=node_id,
        label=_optional_text(payload.get("label")),
        relation=(payload.get("relation") or "implements").strip(),
        created_by=str(g.user.id),
    )
    db.session.add(link)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise ConflictError("Design link already exists", code="duplicate_design_link") from None
    return ok(_serialize_link(link), status=201)


@bp.get("/mockups/<uuid:artifact_id>/preview")
def retrieve_mockup_preview(artifact_id):
    _require("design:read")
    artifact = _get_mockup(artifact_id)
    reference = _reference(artifact)
    refresh = request.args.get("refresh", "false").lower() == "true"
    retrieved = None
    if refresh:
        retrieved = PenpotAdapter(current_app.config).retrieve(reference.file_id)
    return ok(
        {
            "artifact_id": str(artifact.id),
            "version": artifact.current_version,
            "preview_url": reference.preview_url,
            "retrieved": retrieved,
            "capabilities": reference.capabilities,
            "handoff": reference.handoff,
        }
    )


@bp.post("/previews")
def create_preview():
    _require("preview:write")
    org = _org()
    payload = request.get_json(silent=True) or {}
    mockup = _get_mockup(_uuid(payload.get("mockup_id"), "mockup_id"))
    if mockup.status != "approved":
        raise ConflictError("Preview requires an approved mockup", code="mockup_not_approved")
    environment = (payload.get("environment") or "preview").strip().lower()
    if environment in {"production", "prod"}:
        raise ValidationError("Phase 4 previews cannot target production")
    deploy = payload.get("deploy", False) is True
    url = _url(payload.get("url"), "url", required=not deploy)
    if url and urlparse(url).scheme != "https":
        raise ValidationError("preview url must use HTTPS")
    commit_sha = (payload.get("commit_sha") or "").strip()
    if not commit_sha:
        raise ValidationError("commit_sha is required")
    expires_at = _timestamp(payload.get("expires_at"), "expires_at")
    if expires_at <= utcnow():
        raise ValidationError("expires_at must be in the future")
    if expires_at > utcnow() + timedelta(days=30):
        raise ValidationError("preview expiry cannot exceed 30 days")
    access_policy = payload.get("access_policy") or {}
    if not isinstance(access_policy, dict) or access_policy.get("authentication") != "required":
        raise ValidationError("preview access_policy.authentication must be 'required'")
    if access_policy.get("data_class") == "production":
        raise ValidationError("preview cannot use production data")
    change_set = None
    if payload.get("change_set_id"):
        from ..models import ChangeSet

        change_set = ChangeSet.query.filter_by(
            id=_uuid(payload["change_set_id"], "change_set_id"),
            organization_id=org.id,
            project_id=mockup.project_id,
            status="approved",
        ).first()
        if change_set is None:
            raise ConflictError("change_set_id must reference an approved change set")
    version = service.current_version(mockup)
    deployment = None
    if deploy:
        manifest = {
            "project_id": str(mockup.project_id),
            "mockup_id": str(mockup.id),
            "mockup_version": mockup.current_version,
            "mockup_hash": version.content_hash,
            "change_set_id": str(change_set.id) if change_set else None,
            "commit_sha": commit_sha,
            "environment": environment,
            "access_policy": access_policy,
            "expires_at": expires_at.isoformat(),
        }
        factory = current_app.config.get("PREVIEW_DEPLOYMENT_FACTORY")
        adapter = factory() if factory else WebhookPreviewDeploymentAdapter(current_app.config)
        deployment = adapter.provision(manifest)
        url = deployment.url
    evidence = payload.get("evidence") or {}
    if not isinstance(evidence, dict):
        raise ValidationError("evidence must be an object")
    if deployment:
        evidence = {
            **evidence,
            "deployment_id": deployment.deployment_id,
            "deployment_evidence": deployment.evidence,
        }
    preview = PreviewDeployment(
        id=new_uuid(),
        organization_id=org.id,
        project_id=mockup.project_id,
        mockup_artifact_id=mockup.id,
        mockup_version=mockup.current_version,
        mockup_hash=version.content_hash,
        change_set_id=change_set.id if change_set else None,
        commit_sha=commit_sha,
        environment=environment,
        url=url,
        access_policy=access_policy,
        evidence=evidence,
        expires_at=expires_at,
        created_by=str(g.user.id),
    )
    db.session.add(preview)
    db.session.commit()
    _audit(
        "preview.created",
        preview,
        {
            "mockup_id": str(mockup.id),
            "commit_sha": commit_sha,
            "deployed": bool(deployment),
            "deployment_id": deployment.deployment_id if deployment else None,
        },
    )
    return ok(_serialize_preview(preview), status=201)


@bp.get("/previews")
def list_previews():
    _require("preview:read")
    query = PreviewDeployment.query.filter_by(organization_id=_org().id)
    if request.args.get("project_id"):
        query = query.filter_by(project_id=_uuid(request.args["project_id"], "project_id"))
    return ok(
        [
            _serialize_preview(item)
            for item in query.order_by(PreviewDeployment.created_at.desc()).all()
        ]
    )


@bp.get("/previews/<uuid:preview_id>")
def get_preview(preview_id):
    _require("preview:read")
    return ok(_serialize_preview(_get_preview(preview_id)))


@bp.post("/previews/<uuid:preview_id>/revoke")
def revoke_preview(preview_id):
    _require("preview:write")
    preview = _get_preview(preview_id)
    if preview.status in {"revoked", "expired"}:
        raise ConflictError("Preview is already inactive", code="invalid_preview_state")
    preview.status = "revoked"
    db.session.commit()
    _audit("preview.revoked", preview, {})
    return ok(_serialize_preview(preview))


@bp.post("/acceptance/sessions")
def create_acceptance_session():
    _require("acceptance:write")
    org = _org()
    payload = request.get_json(silent=True) or {}
    preview = _get_preview(_uuid(payload.get("preview_id"), "preview_id"))
    _assert_preview_active(preview)
    criteria = _criteria(payload.get("criteria"))
    work_item = None
    if payload.get("work_item_id"):
        work_item = WorkItem.query.filter_by(
            id=_uuid(payload["work_item_id"], "work_item_id"),
            project_id=preview.project_id,
            organization_id=org.id,
        ).first()
        if work_item is None:
            raise NotFoundError("Work item not found in the preview project")
    session = AcceptanceSession(
        id=new_uuid(),
        organization_id=org.id,
        project_id=preview.project_id,
        preview_id=preview.id,
        work_item_id=work_item.id if work_item else None,
        scenario_guidance=_string_list(payload.get("scenario_guidance"), "scenario_guidance"),
        criteria=criteria,
        created_by=str(g.user.id),
    )
    db.session.add(session)
    db.session.commit()
    _audit("acceptance_session.created", session, {"preview_id": str(preview.id)})
    return ok(_serialize_session(session), status=201)


@bp.get("/acceptance/sessions/<uuid:session_id>")
def get_acceptance_session(session_id):
    _require("acceptance:read")
    return ok(_serialize_session(_get_session(session_id)))


@bp.post("/acceptance/sessions/<uuid:session_id>/results")
def record_acceptance_result(session_id):
    _require("acceptance:write")
    session = _get_session(session_id)
    if session.status in {"accepted", "failed", "cancelled"}:
        raise ConflictError("Acceptance session is terminal", code="invalid_acceptance_state")
    payload = request.get_json(silent=True) or {}
    key = (payload.get("criterion_key") or "").strip()
    allowed = {item["key"] for item in session.criteria}
    if key not in allowed:
        raise ValidationError("criterion_key must reference a session criterion")
    outcome = (payload.get("outcome") or "").strip().lower()
    if outcome not in OUTCOMES:
        raise ValidationError("outcome must be pass, fail, blocked or na")
    defect = None
    if payload.get("defect_id"):
        defect = Defect.query.filter_by(
            id=_uuid(payload["defect_id"], "defect_id"),
            organization_id=_org().id,
            project_id=session.project_id,
        ).first()
        if defect is None:
            raise NotFoundError("Defect not found in the session project")
    result = AcceptanceResult.query.filter_by(session_id=session.id, criterion_key=key).first()
    if result is None:
        result = AcceptanceResult(
            id=new_uuid(),
            organization_id=_org().id,
            project_id=session.project_id,
            session_id=session.id,
            criterion_key=key,
        )
        db.session.add(result)
    result.outcome = outcome
    result.notes = payload.get("notes")
    result.evidence = payload.get("evidence") or {}
    result.defect_id = defect.id if defect else None
    result.recorded_by = str(g.user.id)
    db.session.commit()
    _audit(
        "acceptance_result.recorded",
        result,
        {"session_id": str(session.id), "criterion_key": key, "outcome": outcome},
    )
    return ok(_serialize_result(result), status=201)


@bp.post("/acceptance/sessions/<uuid:session_id>/complete")
def complete_acceptance_session(session_id):
    _require("acceptance:write")
    session = _get_session(session_id)
    if session.status != "open":
        raise ConflictError(
            "Only open acceptance sessions can complete", code="invalid_acceptance_state"
        )
    by_key = {result.criterion_key: result for result in session.results}
    missing = [item["key"] for item in session.criteria if item["key"] not in by_key]
    if missing:
        raise ConflictError(
            "Every acceptance criterion needs a result",
            code="acceptance_results_required",
            details={"missing": missing},
        )
    failing = [key for key, result in by_key.items() if result.outcome in {"fail", "blocked"}]
    blocking_defects = [
        str(defect.id)
        for defect in session.defects
        if defect.severity in {"critical", "high"} and defect.status != "closed"
    ]
    if blocking_defects:
        failing.append("blocking-defects")
    if failing:
        session.status = "failed"
    else:
        session.status = "accepted"
    session.evidence = request.get_json(silent=True) or {}
    session.completed_by = str(g.user.id)
    session.completed_at = utcnow()
    db.session.commit()
    _audit("acceptance_session.completed", session, {"status": session.status, "failing": failing})
    return ok(_serialize_session(session))


@bp.post("/defects")
def create_defect():
    _require("defect:write")
    org = _org()
    payload = request.get_json(silent=True) or {}
    title = _title(payload.get("title"))
    severity = (payload.get("severity") or "medium").strip().lower()
    if severity not in DEFECT_SEVERITIES:
        raise ValidationError("severity must be critical, high, medium or low")
    session = (
        _get_session(_uuid(payload["session_id"], "session_id"))
        if payload.get("session_id")
        else None
    )
    project_id = session.project_id if session else _uuid(payload.get("project_id"), "project_id")
    work_item = None
    if payload.get("work_item_id"):
        work_item = WorkItem.query.filter_by(
            id=_uuid(payload["work_item_id"], "work_item_id"),
            project_id=project_id,
            organization_id=org.id,
        ).first()
        if work_item is None:
            raise NotFoundError("Work item not found in the defect project")
    expected = (payload.get("expected") or "").strip()
    actual = (payload.get("actual") or "").strip()
    if not expected or not actual:
        raise ValidationError("expected and actual are required")
    defect = Defect(
        id=new_uuid(),
        organization_id=org.id,
        project_id=project_id,
        session_id=session.id if session else None,
        work_item_id=work_item.id if work_item else None,
        title=title,
        severity=severity,
        reproduction_steps=_string_list(payload.get("reproduction_steps"), "reproduction_steps"),
        expected=expected,
        actual=actual,
        attachments=payload.get("attachments") or [],
        regression_test_required=payload.get("regression_test_required", True) is not False,
        created_by=str(g.user.id),
    )
    db.session.add(defect)
    db.session.commit()
    _audit("defect.created", defect, {"project_id": str(project_id), "severity": severity})
    return ok(_serialize_defect(defect), status=201)


@bp.get("/defects")
def list_defects():
    _require("defect:read")
    query = Defect.query.filter_by(organization_id=_org().id)
    if request.args.get("project_id"):
        query = query.filter_by(project_id=_uuid(request.args["project_id"], "project_id"))
    if request.args.get("status"):
        query = query.filter_by(status=request.args["status"])
    return ok([_serialize_defect(item) for item in query.order_by(Defect.created_at.desc()).all()])


@bp.patch("/defects/<uuid:defect_id>")
def update_defect(defect_id):
    _require("defect:write")
    defect = Defect.query.filter_by(id=defect_id, organization_id=_org().id).first()
    if defect is None:
        raise NotFoundError("Defect not found")
    payload = request.get_json(silent=True) or {}
    if "status" in payload:
        status = (payload["status"] or "").strip().lower()
        if status not in DEFECT_STATUSES:
            raise ValidationError("unsupported defect status")
        if status == "closed" and defect.regression_test_required:
            evidence = payload.get("regression_evidence") or defect.regression_evidence
            if not isinstance(evidence, dict) or evidence.get("status") != "passed":
                raise ConflictError(
                    "A defect requiring regression evidence can close only with a passed test",
                    code="regression_evidence_required",
                )
            defect.regression_evidence = evidence
        defect.status = status
        if status == "closed":
            defect.resolved_by = str(g.user.id)
            defect.resolved_at = utcnow()
        elif status == "reopened":
            defect.resolved_by = None
            defect.resolved_at = None
    if "regression_evidence" in payload:
        if not isinstance(payload["regression_evidence"], dict):
            raise ValidationError("regression_evidence must be an object")
        defect.regression_evidence = payload["regression_evidence"]
    if "actual" in payload and payload["actual"]:
        defect.actual = payload["actual"].strip()
    db.session.commit()
    _audit(
        "defect.updated",
        defect,
        {"status": defect.status, "fields": sorted(payload.keys())},
    )
    return ok(_serialize_defect(defect))


def _serialize_mockup(artifact, *, include_content=False):
    data = service.serialize_artifact(artifact, include_content=include_content)
    data["source_architecture"] = {
        "artifact_id": str(artifact.source_artifact_id),
        "version": artifact.source_artifact_version,
        "hash": artifact.source_artifact_hash,
    }
    reference = _reference(artifact)
    data["design_reference"] = {
        "id": str(reference.id),
        "provider": reference.provider,
        "file_id": reference.file_id,
        "file_url": reference.file_url,
        "preview_url": reference.preview_url,
        "provider_metadata": reference.provider_metadata,
        "capabilities": reference.capabilities,
        "handoff": reference.handoff,
        "links": [_serialize_link(link) for link in reference.links],
    }
    data["comments"] = [_serialize_comment(comment) for comment in artifact.comments]
    return data


def _serialize_comment(comment):
    return {
        "id": str(comment.id),
        "version": comment.artifact_version,
        "anchor": comment.anchor,
        "body": comment.body,
        "status": comment.status,
        "created_by": comment.created_by,
        "resolved_by": comment.resolved_by,
        "created_at": comment.created_at.isoformat(),
        "resolved_at": comment.resolved_at.isoformat() if comment.resolved_at else None,
    }


def _serialize_link(link):
    return {
        "id": str(link.id),
        "work_item_id": str(link.work_item_id),
        "page_id": link.page_id,
        "node_id": link.node_id,
        "label": link.label,
        "relation": link.relation,
        "created_by": link.created_by,
        "created_at": link.created_at.isoformat(),
    }


def _serialize_preview(preview):
    status = preview.status
    if status == "active" and preview.expires_at <= utcnow():
        status = "expired"
    return {
        "id": str(preview.id),
        "project_id": str(preview.project_id),
        "mockup_id": str(preview.mockup_artifact_id),
        "mockup_version": preview.mockup_version,
        "mockup_hash": preview.mockup_hash,
        "change_set_id": str(preview.change_set_id) if preview.change_set_id else None,
        "commit_sha": preview.commit_sha,
        "environment": preview.environment,
        "url": preview.url,
        "status": status,
        "access_policy": preview.access_policy,
        "evidence": preview.evidence,
        "expires_at": preview.expires_at.isoformat(),
        "created_by": preview.created_by,
        "created_at": preview.created_at.isoformat(),
    }


def _serialize_session(session):
    return {
        "id": str(session.id),
        "project_id": str(session.project_id),
        "preview_id": str(session.preview_id),
        "work_item_id": str(session.work_item_id) if session.work_item_id else None,
        "status": session.status,
        "scenario_guidance": session.scenario_guidance,
        "criteria": session.criteria,
        "evidence": session.evidence,
        "results": [_serialize_result(result) for result in session.results],
        "defects": [_serialize_defect(defect) for defect in session.defects],
        "created_by": session.created_by,
        "completed_by": session.completed_by,
        "created_at": session.created_at.isoformat(),
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
    }


def _serialize_result(result):
    return {
        "id": str(result.id),
        "criterion_key": result.criterion_key,
        "outcome": result.outcome,
        "notes": result.notes,
        "evidence": result.evidence,
        "defect_id": str(result.defect_id) if result.defect_id else None,
        "recorded_by": result.recorded_by,
        "created_at": result.created_at.isoformat(),
    }


def _serialize_defect(defect):
    return {
        "id": str(defect.id),
        "project_id": str(defect.project_id),
        "session_id": str(defect.session_id) if defect.session_id else None,
        "work_item_id": str(defect.work_item_id) if defect.work_item_id else None,
        "title": defect.title,
        "severity": defect.severity,
        "status": defect.status,
        "reproduction_steps": defect.reproduction_steps,
        "expected": defect.expected,
        "actual": defect.actual,
        "attachments": defect.attachments,
        "regression_test_required": defect.regression_test_required,
        "regression_evidence": defect.regression_evidence,
        "created_by": defect.created_by,
        "resolved_by": defect.resolved_by,
        "created_at": defect.created_at.isoformat(),
        "resolved_at": defect.resolved_at.isoformat() if defect.resolved_at else None,
    }


def _get_mockup(artifact_id):
    artifact = Artifact.query.filter_by(
        id=artifact_id, organization_id=_org().id, artifact_type="mockup"
    ).first()
    if artifact is None:
        raise NotFoundError("Mockup not found")
    return artifact


def _reference(artifact):
    reference = DesignReference.query.filter_by(
        artifact_id=artifact.id, organization_id=_org().id
    ).first()
    if reference is None:
        raise NotFoundError("Design reference not found")
    return reference


def _get_preview(preview_id):
    preview = PreviewDeployment.query.filter_by(id=preview_id, organization_id=_org().id).first()
    if preview is None:
        raise NotFoundError("Preview deployment not found")
    return preview


def _get_session(session_id):
    session = AcceptanceSession.query.filter_by(id=session_id, organization_id=_org().id).first()
    if session is None:
        raise NotFoundError("Acceptance session not found")
    return session


def _assert_preview_active(preview):
    if preview.status != "active" or preview.expires_at <= utcnow():
        raise ConflictError("Preview is not active or has expired", code="preview_not_active")


def _org():
    org = getattr(g, "organization", None)
    if org is None:
        raise AuthenticationError("Authenticated organization not found")
    return org


def _require(scope):
    from ..auth.roles import has_scope

    if g.user is None or not has_scope(g.user, scope):
        raise AuthenticationError(f"{scope} scope required")


def _uuid(value, field):
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValidationError(f"{field} must be a valid UUID") from exc


def _title(value):
    title = (value or "").strip()
    if not title or len(title) > 200:
        raise ValidationError("title is required (max 200 characters)")
    return title


def _url(value, field, *, required):
    value = (value or "").strip()
    if not value and not required:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValidationError(f"{field} must be an absolute HTTP(S) URL")
    return value


def _timestamp(value, field):
    if not value:
        raise ValidationError(f"{field} is required")
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as exc:
        raise ValidationError(f"{field} must be an ISO-8601 timestamp") from exc


def _optional_text(value):
    value = (value or "").strip()
    return value or None


def _string_list(value, field):
    if value is None:
        return []
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValidationError(f"{field} must be a list of non-empty strings")
    return [item.strip() for item in value]


def _criteria(value):
    if not isinstance(value, list) or not value:
        raise ValidationError("criteria must be a non-empty list")
    result = []
    seen = set()
    for index, item in enumerate(value, 1):
        if isinstance(item, str):
            key, title = f"criterion-{index}", item.strip()
        elif isinstance(item, dict):
            key = (item.get("key") or f"criterion-{index}").strip()
            title = (item.get("title") or "").strip()
        else:
            raise ValidationError("each criterion must be a string or object")
        if not key or not title or len(key) > 64 or key in seen:
            raise ValidationError("criteria need unique keys and non-empty titles")
        seen.add(key)
        result.append({"key": key, "title": title})
    return result


def _audit(action, target, metadata):
    record_audit(
        action=action,
        actor_id=str(g.user.id),
        target_type=target.__class__.__name__.lower(),
        target_id=target.id,
        organization_id=_org().id,
        metadata=metadata,
    )
