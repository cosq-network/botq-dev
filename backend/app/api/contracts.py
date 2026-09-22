"""Explicit request contract field definitions for every mutating API family.

The controllers still own lifecycle and authorization rules.  These definitions
own the transport shape so OpenAPI and cookie-authenticated request validation
do not fall back to an untyped ``payload`` object.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

JsonObject = dict[str, Any]

EXPLICIT_FIELDS: dict[str, dict[str, type]] = {
    "api.planning.cancel_agent_run": {"reason": str},
    "api.planning.pause_agent_run": {"reason": str},
    "api.planning.start_agent_run": {},
    "api.planning.checkpoint_agent_run": {"state": JsonObject, "evidence": JsonObject, "current_step": str},
    "api.auth.logout": {},
    "api.architecture.revise_package": {"content": JsonObject, "change_summary": str},
    "api.architecture.resolve_comment": {},
    "api.architecture.approve_package": {},
    "api.architecture.reject_package": {},
    "api.architecture.request_changes_package": {},
    "api.architecture.submit_package": {},
    "api.architecture.waive_package": {"reason": str, "expires_at": str},
    "api.planning.approve_change_set": {},
    "api.planning.self_review_change_set": {"review": JsonObject},
    "api.planning.submit_change_set": {},
    "api.planning.approve_plan": {},
    "api.planning.reject_plan": {},
    "api.planning.request_changes_plan": {},
    "api.planning.submit_plan": {},
    "api.planning.revise_plan": {"content": JsonObject, "change_summary": str},
    "api.release.approve_deployment_plan": {},
    "api.release.submit_deployment_plan": {},
    "api.release.rollback_deployment": {},
    "api.design.complete_acceptance_session": {"evidence": JsonObject},
    "api.design.revise_mockup": {"content": JsonObject, "change_summary": str},
    "api.design.add_mockup_comment": {"body": str, "anchor": JsonObject, "version": int},
    "api.design.approve_mockup": {},
    "api.design.resolve_mockup_comment": {},
    "api.design.request_changes_mockup": {},
    "api.design.submit_mockup": {},
    "api.design.revoke_preview": {},
    "api.diagnostics.retention_execute": {"dry_run": bool, "confirm": bool},
    "api.orgs.update_org_gate_policy": {
        "approval_mode": str,
        "require_gate_decisions": bool,
        "require_project_responsibility_assignment": bool,
        "allow_waivers": bool,
        "require_previous_gate_closed": bool,
        "auto_sync_evidence": bool,
    },
    "api.orgs.replace_org_user_roles": {"roles": list[str]},
    "api.projects.archive_project": {},
    "api.gates.update_project_gate_policy": {
        "approval_mode": str,
        "require_gate_decisions": bool,
        "require_project_responsibility_assignment": bool,
        "allow_waivers": bool,
        "require_previous_gate_closed": bool,
        "auto_sync_evidence": bool,
    },
    "api.gates.close_gate": {},
    "api.gates.evaluate_gate": {},
    "api.gates.sync_gate": {},
    "api.gates.decide_gate": {
        "responsibility_type": str,
        "decision": str,
        "comment": str,
    },
    "api.git.revoke": {},
    "api.git.rotate_key": {},
    "api.git.sync": {},
    "api.git.test_connection": {},
    "api.release.approve_release": {},
    "api.release.package_release": {},
    "api.release.create_deployment_plan": {"release_id": UUID, "environment": str, "content": JsonObject},
    "api.requirements.apply_work_items": {},
    "api.requirements.analyze_baseline": {},
    "api.requirements.approve_baseline": {},
    "api.requirements.cancel_baseline": {},
    "api.requirements.reject_baseline": {},
    "api.requirements.request_changes_baseline": {},
    "api.requirements.submit_baseline": {},
    "api.requirements.waive_baseline": {"reason": str, "expires_at": str},
    "api.secrets.revoke_secret": {},
    "api.secrets.verify_secret": {},
    "api.work_items.add_dependency": {"depends_on_id": UUID},
}
