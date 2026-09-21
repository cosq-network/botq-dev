class Scopes:
    ADMIN = "admin"
    PROJECT_READ = "project:read"
    PROJECT_WRITE = "project:write"
    REQUIREMENT_READ = "requirement:read"
    REQUIREMENT_WRITE = "requirement:write"
    APPROVAL = "approval"
    REPOSITORY_READ = "repository:read"
    REPOSITORY_WRITE = "repository:write"
    SECRET_MANAGE = "secret:manage"  # nosec B105 - authorization scope name.
    SECRET_INJECT = "secret:inject"  # nosec B105 - authorization scope name.
    SANDBOX_READ = "sandbox:read"
    SANDBOX_RUN = "sandbox:run"
    AUDIT_READ = "audit:read"
    CONFIG_READ = "config:read"
    CONFIG_MANAGE = "config:manage"
    COST_READ = "cost:read"
    INTEGRATION_MANAGE = "integration:manage"
    DESIGN_READ = "design:read"
    DESIGN_WRITE = "design:write"
    PLAN_READ = "plan:read"
    PLAN_WRITE = "plan:write"
    AGENT_RUN_READ = "agent_run:read"
    AGENT_RUN_RUN = "agent_run:run"
    CHANGESET_READ = "changeset:read"
    CHANGESET_WRITE = "changeset:write"
    PREVIEW_READ = "preview:read"
    PREVIEW_WRITE = "preview:write"
    ACCEPTANCE_READ = "acceptance:read"
    ACCEPTANCE_WRITE = "acceptance:write"
    DEFECT_READ = "defect:read"
    DEFECT_WRITE = "defect:write"
    RELEASE_READ = "release:read"
    RELEASE_WRITE = "release:write"
    DEPLOYMENT_READ = "deployment:read"
    DEPLOYMENT_WRITE = "deployment:write"
    GATE_APPROVE = "gate:approve"
    GATE_CLOSE = "gate:close"


ALL_SCOPES = {value for _, value in Scopes.__dict__.items() if isinstance(value, str)}


SYSTEM_ROLES: dict[str, list[str]] = {
    "gate_automation": [
        Scopes.PROJECT_READ,
        Scopes.GATE_APPROVE,
        Scopes.GATE_CLOSE,
    ],
    "organization_administrator": sorted(ALL_SCOPES),
    "product_owner": [
        Scopes.PROJECT_READ,
        Scopes.PROJECT_WRITE,
        Scopes.REQUIREMENT_READ,
        Scopes.REQUIREMENT_WRITE,
        Scopes.APPROVAL,
        Scopes.REPOSITORY_READ,
        Scopes.SANDBOX_READ,
        Scopes.CONFIG_READ,
        Scopes.COST_READ,
        Scopes.DESIGN_READ,
        Scopes.DESIGN_WRITE,
        Scopes.PLAN_READ,
        Scopes.PLAN_WRITE,
        Scopes.AGENT_RUN_READ,
        Scopes.AGENT_RUN_RUN,
        Scopes.CHANGESET_READ,
        Scopes.CHANGESET_WRITE,
        Scopes.PREVIEW_READ,
        Scopes.PREVIEW_WRITE,
        Scopes.ACCEPTANCE_READ,
        Scopes.ACCEPTANCE_WRITE,
        Scopes.DEFECT_READ,
        Scopes.DEFECT_WRITE,
        Scopes.RELEASE_READ,
        Scopes.DEPLOYMENT_READ,
    ],
    "architect": [
        Scopes.PROJECT_READ,
        Scopes.REQUIREMENT_READ,
        Scopes.APPROVAL,
        Scopes.REPOSITORY_READ,
        Scopes.SANDBOX_READ,
        Scopes.CONFIG_READ,
        Scopes.COST_READ,
        Scopes.DESIGN_READ,
        Scopes.DESIGN_WRITE,
        Scopes.PREVIEW_READ,
        Scopes.ACCEPTANCE_READ,
        Scopes.DEFECT_READ,
        Scopes.PLAN_READ,
        Scopes.PLAN_WRITE,
        Scopes.AGENT_RUN_READ,
    ],
    "developer": [
        Scopes.PROJECT_READ,
        Scopes.REQUIREMENT_READ,
        Scopes.REPOSITORY_READ,
        Scopes.REPOSITORY_WRITE,
        Scopes.SANDBOX_READ,
        Scopes.SANDBOX_RUN,
        Scopes.COST_READ,
        Scopes.PLAN_READ,
        Scopes.AGENT_RUN_READ,
        Scopes.AGENT_RUN_RUN,
        Scopes.CHANGESET_READ,
        Scopes.CHANGESET_WRITE,
        Scopes.PREVIEW_READ,
        Scopes.ACCEPTANCE_READ,
        Scopes.DEFECT_READ,
    ],
    "designer": [
        Scopes.PROJECT_READ,
        Scopes.REQUIREMENT_READ,
        Scopes.APPROVAL,
        Scopes.REPOSITORY_READ,
        Scopes.SANDBOX_READ,
        Scopes.DESIGN_READ,
        Scopes.DESIGN_WRITE,
        Scopes.PREVIEW_READ,
    ],
    "qa_engineer": [
        Scopes.PROJECT_READ,
        Scopes.REQUIREMENT_READ,
        Scopes.APPROVAL,
        Scopes.SANDBOX_READ,
        Scopes.SANDBOX_RUN,
        Scopes.AUDIT_READ,
        Scopes.PLAN_READ,
        Scopes.AGENT_RUN_READ,
        Scopes.CHANGESET_READ,
        Scopes.PREVIEW_READ,
        Scopes.ACCEPTANCE_READ,
        Scopes.ACCEPTANCE_WRITE,
        Scopes.DEFECT_READ,
        Scopes.DEFECT_WRITE,
        Scopes.RELEASE_READ,
        Scopes.DEPLOYMENT_READ,
    ],
    "security_approver": [
        Scopes.PROJECT_READ,
        Scopes.REQUIREMENT_READ,
        Scopes.APPROVAL,
        Scopes.REPOSITORY_READ,
        Scopes.SANDBOX_READ,
        Scopes.SECRET_MANAGE,
        Scopes.SECRET_INJECT,
        Scopes.AUDIT_READ,
        Scopes.CONFIG_READ,
        Scopes.DESIGN_READ,
        Scopes.PLAN_READ,
        Scopes.AGENT_RUN_READ,
        Scopes.CHANGESET_READ,
        Scopes.PREVIEW_READ,
        Scopes.ACCEPTANCE_READ,
        Scopes.DEFECT_READ,
        Scopes.RELEASE_READ,
        Scopes.RELEASE_WRITE,
        Scopes.DEPLOYMENT_READ,
        Scopes.DEPLOYMENT_WRITE,
    ],
    "release_manager": [
        Scopes.PROJECT_READ,
        Scopes.REPOSITORY_READ,
        Scopes.REPOSITORY_WRITE,
        Scopes.APPROVAL,
        Scopes.CONFIG_READ,
        Scopes.CONFIG_MANAGE,
        Scopes.COST_READ,
        Scopes.PLAN_READ,
        Scopes.CHANGESET_READ,
        Scopes.PREVIEW_READ,
        Scopes.ACCEPTANCE_READ,
        Scopes.DEFECT_READ,
        Scopes.RELEASE_READ,
        Scopes.RELEASE_WRITE,
        Scopes.DEPLOYMENT_READ,
        Scopes.DEPLOYMENT_WRITE,
    ],
    "operations_approver": [
        Scopes.PROJECT_READ,
        Scopes.APPROVAL,
        Scopes.AUDIT_READ,
        Scopes.CONFIG_READ,
        Scopes.RELEASE_READ,
        Scopes.DEPLOYMENT_READ,
        Scopes.DEPLOYMENT_WRITE,
    ],
    "auditor": [
        Scopes.PROJECT_READ,
        Scopes.AUDIT_READ,
        Scopes.SANDBOX_READ,
        Scopes.COST_READ,
        Scopes.CONFIG_READ,
        Scopes.DESIGN_READ,
        Scopes.PLAN_READ,
        Scopes.AGENT_RUN_READ,
        Scopes.CHANGESET_READ,
        Scopes.PREVIEW_READ,
        Scopes.ACCEPTANCE_READ,
        Scopes.DEFECT_READ,
        Scopes.RELEASE_READ,
        Scopes.DEPLOYMENT_READ,
    ],
    "ai_agent": [
        Scopes.PROJECT_READ,
        Scopes.SANDBOX_RUN,
        Scopes.SANDBOX_READ,
        Scopes.AGENT_RUN_READ,
        Scopes.AGENT_RUN_RUN,
        Scopes.CHANGESET_READ,
        Scopes.CHANGESET_WRITE,
    ],
}


def scopes_for_user(user) -> set[str]:
    granted: set[str] = set()
    for role in user.roles or []:
        for scope in role.scopes or []:
            if scope == Scopes.ADMIN:
                granted.update(ALL_SCOPES)
            else:
                granted.add(scope)
    return granted


def has_scope(user, scope: str) -> bool:
    return scope in scopes_for_user(user)


def default_role_names() -> list[str]:
    return sorted(SYSTEM_ROLES.keys())


def is_known_role(name: str) -> bool:
    return name in SYSTEM_ROLES
