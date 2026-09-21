import uuid
from datetime import datetime
from typing import TypeAlias

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .extensions import db
from .utils import new_uuid, utcnow

uuid_pk: TypeAlias = object


class FlexibleUuid(TypeDecorator):
    """Accept UUID objects and API-shaped UUID strings in ORM predicates."""

    impl = Uuid
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


user_roles = db.Table(
    "user_roles",
    db.Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    db.Column("role_id", Uuid, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

work_item_dependencies = db.Table(
    "work_item_dependencies",
    db.Column(
        "work_item_id",
        Uuid,
        ForeignKey("work_items.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "depends_on_id",
        Uuid,
        ForeignKey("work_items.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Organization(db.Model):
    __tablename__ = "organizations"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    users = relationship("User", back_populates="organization", lazy="selectin")
    roles = relationship(
        "Role", back_populates="organization", lazy="selectin", cascade="all, delete-orphan"
    )
    projects = relationship("Project", back_populates="organization", lazy="selectin")
    secrets = relationship("Secret", back_populates="organization", lazy="selectin")
    integrations = relationship("Integration", back_populates="organization", lazy="selectin")

    __table_args__ = (UniqueConstraint("slug", name="uq_organizations_slug"),)


class User(db.Model):
    __tablename__ = "users"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_sub: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    organization = relationship("Organization", back_populates="users")
    roles = relationship("Role", secondary=user_roles, back_populates="users", lazy="selectin")
    tokens = relationship("Token", back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("organization_id", "email", name="uq_users_org_email"),)


class Role(db.Model):
    __tablename__ = "roles"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    organization = relationship("Organization", back_populates="roles")
    users = relationship("User", secondary=user_roles, back_populates="roles", lazy="selectin")

    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_roles_org_name"),)


class Project(db.Model):
    __tablename__ = "projects"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    key: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    lifecycle_state: Mapped[str] = mapped_column(String(32), nullable=False, default="requirements")
    default_branch: Mapped[str] = mapped_column(String(128), nullable=False, default="main")
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    organization = relationship("Organization", back_populates="projects")
    repository = relationship(
        "RepositoryConnection",
        back_populates="project",
        uselist=False,
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "key", name="uq_projects_org_key"),
        Index("ix_projects_lifecycle", "organization_id", "lifecycle_state"),
    )


class ProjectResponsibilityAssignment(db.Model):
    """Project-scoped human responsibility assignment with an auditable lifetime."""

    __tablename__ = "project_responsibility_assignments"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    responsibility_type: Mapped[str] = mapped_column(String(64), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    segregation_group: Mapped[str | None] = mapped_column(String(64), nullable=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    assigned_by: Mapped[uuid_pk | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    project = relationship("Project")
    user = relationship("User", foreign_keys=[user_id])
    assigner = relationship("User", foreign_keys=[assigned_by])

    __table_args__ = (
        Index(
            "ix_project_responsibility_active",
            "project_id",
            "responsibility_type",
            "is_primary",
            "effective_from",
        ),
    )


class ProjectGate(db.Model):
    """Explicit lifecycle gate state for a project."""

    __tablename__ = "project_gates"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    required_evidence: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_by: Mapped[uuid_pk | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reopened_by: Mapped[uuid_pk | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    reopen_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    project = relationship("Project")
    evidence = relationship(
        "ProjectGateEvidence", back_populates="gate", cascade="all, delete-orphan", lazy="selectin"
    )
    decisions = relationship(
        "ProjectGateDecision", back_populates="gate", cascade="all, delete-orphan", lazy="selectin"
    )
    history = relationship(
        "ProjectGateHistory",
        back_populates="gate",
        cascade="all, delete-orphan",
        order_by="ProjectGateHistory.created_at",
        lazy="selectin",
    )

    __table_args__ = (UniqueConstraint("project_id", "number", name="uq_project_gate_number"),)


class ProjectGateEvidence(db.Model):
    __tablename__ = "project_gate_evidence"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    gate_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("project_gates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(96), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    producer_type: Mapped[str] = mapped_column(String(32), nullable=False, default="api")
    command: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    diagnostics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[uuid_pk] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    gate = relationship("ProjectGate", back_populates="evidence")

    __table_args__ = (
        UniqueConstraint("gate_id", "key", name="uq_project_gate_evidence_key"),
        UniqueConstraint("gate_id", "idempotency_key", name="uq_project_gate_evidence_idempotency"),
    )


class ProjectGateDecision(db.Model):
    __tablename__ = "project_gate_decisions"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    gate_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("project_gates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    responsibility_type: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[uuid_pk] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    decider_type: Mapped[str] = mapped_column(String(32), nullable=False, default="human")
    approval_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="human_api")
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    evidence_hashes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False, default="gate-policy-v1")
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    gate = relationship("ProjectGate", back_populates="decisions")

    __table_args__ = (
        UniqueConstraint("gate_id", "responsibility_type", "idempotency_key", name="uq_project_gate_decision_idempotency"),
    )


class ProjectGateHistory(db.Model):
    __tablename__ = "project_gate_history"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    gate_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("project_gates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[uuid_pk | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    gate = relationship("ProjectGate", back_populates="history")

    __table_args__ = (
        UniqueConstraint("gate_id", "action", "idempotency_key", name="uq_project_gate_history_idempotency"),
    )


class RepositoryConnection(db.Model):
    __tablename__ = "repository_connections"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    ssh_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    host_fingerprint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deploy_key_public: Mapped[str | None] = mapped_column(Text, nullable=True)
    deploy_key_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scope: Mapped[str] = mapped_column(String(8), nullable=False, default="rw")
    default_branch: Mapped[str] = mapped_column(String(128), nullable=False, default="main")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    project = relationship("Project", back_populates="repository")


class AuditEvent(db.Model):
    __tablename__ = "audit_events"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk | None] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False, default="success")
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_audit_org_created", "organization_id", "created_at"),
        Index("ix_audit_corr", "correlation_id"),
    )


class Secret(db.Model):
    __tablename__ = "secrets"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    encrypted_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    secret_store: Mapped[str] = mapped_column(String(32), nullable=False, default="local")
    purpose: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_rotated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    organization = relationship("Organization", back_populates="secrets")

    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_secrets_org_name"),)


class Integration(db.Model):
    __tablename__ = "integrations"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    capability: Mapped[str] = mapped_column(String(64), nullable=False)
    config_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    organization = relationship("Organization", back_populates="integrations")

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider",
            "capability",
            name="uq_integrations_org_provider_capability",
        ),
    )


class Token(db.Model):
    __tablename__ = "auth_tokens"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user = relationship("User", back_populates="tokens")


class RequirementBaseline(db.Model):
    __tablename__ = "requirement_baselines"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    project = relationship("Project")
    versions = relationship(
        "RequirementBaselineVersion",
        back_populates="baseline",
        order_by="RequirementBaselineVersion.version",
        lazy="selectin",
    )

    __table_args__ = (Index("ix_requirement_baselines_project_status", "project_id", "status"),)


class RequirementBaselineVersion(db.Model):
    __tablename__ = "requirement_baseline_versions"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    baseline_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("requirement_baselines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    change_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    baseline = relationship("RequirementBaseline", back_populates="versions")
    analyses = relationship(
        "RequirementAnalysis", back_populates="baseline_version", lazy="selectin"
    )

    __table_args__ = (UniqueConstraint("baseline_id", "version", name="uq_requirement_version"),)


class WorkItem(db.Model):
    __tablename__ = "work_items"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    parent_id: Mapped[uuid_pk | None] = mapped_column(
        Uuid, ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    acceptance_criteria: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    risk: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    owner_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    release_target: Mapped[str | None] = mapped_column(String(64), nullable=True)
    estimate: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_baseline_id: Mapped[uuid_pk | None] = mapped_column(
        Uuid, ForeignKey("requirement_baselines.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_analysis_id: Mapped[uuid_pk | None] = mapped_column(
        FlexibleUuid,
        ForeignKey("requirement_analyses.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_refs: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    is_derived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    project = relationship("Project")
    source_analysis = relationship("RequirementAnalysis", back_populates="work_items")
    parent = relationship("WorkItem", remote_side=[id], backref="children")
    dependencies = relationship(
        "WorkItem",
        secondary=work_item_dependencies,
        primaryjoin="WorkItem.id == work_item_dependencies.c.work_item_id",
        secondaryjoin="WorkItem.id == work_item_dependencies.c.depends_on_id",
        backref="dependents",
    )

    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_work_items_project_code"),
        UniqueConstraint("project_id", "number", name="uq_work_items_project_number"),
        Index("ix_work_items_project_kind", "project_id", "kind"),
    )


class RequirementAnalysis(db.Model):
    """An immutable, version-bound requirement decomposition and analysis run."""

    __tablename__ = "requirement_analyses"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    baseline_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("requirement_baselines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    baseline_version_id: Mapped[uuid_pk] = mapped_column(
        Uuid,
        ForeignKey("requirement_baseline_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    baseline_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="completed")
    summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    proposed_work_items: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    baseline = relationship("RequirementBaseline")
    baseline_version = relationship("RequirementBaselineVersion", back_populates="analyses")
    findings = relationship(
        "RequirementFinding",
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="RequirementFinding.created_at",
        lazy="selectin",
    )
    work_items = relationship("WorkItem", back_populates="source_analysis", lazy="selectin")

    __table_args__ = (
        Index(
            "ix_requirement_analyses_baseline_version",
            "baseline_id",
            "baseline_version_number",
        ),
        Index("ix_requirement_analyses_org_created", "organization_id", "created_at"),
    )


class RequirementFinding(db.Model):
    """A reviewable finding produced by a requirement analysis run."""

    __tablename__ = "requirement_findings"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    analysis_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("requirement_analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    analysis = relationship("RequirementAnalysis", back_populates="findings")

    __table_args__ = (
        UniqueConstraint("analysis_id", "fingerprint", name="uq_requirement_finding_fingerprint"),
        Index("ix_requirement_findings_analysis_status", "analysis_id", "status"),
    )


class Artifact(db.Model):
    """Versioned design, plan, or implementation artifact."""

    __tablename__ = "artifacts"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    source_baseline_id: Mapped[uuid_pk | None] = mapped_column(
        Uuid, ForeignKey("requirement_baselines.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_baseline_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_baseline_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_artifact_id: Mapped[uuid_pk | None] = mapped_column(
        Uuid, ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_artifact_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_artifact_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    project = relationship("Project")
    versions = relationship(
        "ArtifactVersion",
        back_populates="artifact",
        order_by="ArtifactVersion.version",
        lazy="selectin",
    )
    comments = relationship(
        "DesignComment", back_populates="artifact", cascade="all, delete-orphan", lazy="selectin"
    )
    decisions = relationship(
        "ArchitectureDecisionRecord",
        back_populates="artifact",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_artifacts_project_type_status", "project_id", "artifact_type", "status"),
    )


class ArtifactVersion(db.Model):
    __tablename__ = "artifact_versions"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    change_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    artifact = relationship("Artifact", back_populates="versions")

    __table_args__ = (UniqueConstraint("artifact_id", "version", name="uq_artifact_version"),)


class ArchitectureDecisionRecord(db.Model):
    __tablename__ = "architecture_decision_records"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_version: Mapped[int] = mapped_column(Integer, nullable=False)
    key: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    context: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    consequences: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="accepted")
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    artifact = relationship("Artifact", back_populates="decisions")

    __table_args__ = (UniqueConstraint("artifact_id", "key", name="uq_architecture_decision_key"),)


class DesignComment(db.Model):
    __tablename__ = "design_comments"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_version: Mapped[int] = mapped_column(Integer, nullable=False)
    anchor: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    artifact = relationship("Artifact", back_populates="comments")


class DesignReference(db.Model):
    """External design-file pointer; credentials never live in this record."""

    __tablename__ = "design_references"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="penpot")
    file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    file_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    preview_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    provider_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    handoff: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    artifact = relationship("Artifact")
    links = relationship(
        "DesignLink",
        back_populates="design_reference",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (Index("ix_design_references_project_provider", "project_id", "provider"),)


class DesignLink(db.Model):
    """A node/page association between an external design and a work item."""

    __tablename__ = "design_links"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    design_reference_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("design_references.id", ondelete="CASCADE"), nullable=False, index=True
    )
    work_item_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    node_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    relation: Mapped[str] = mapped_column(String(32), nullable=False, default="implements")
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    design_reference = relationship("DesignReference", back_populates="links")
    work_item = relationship("WorkItem")

    __table_args__ = (
        UniqueConstraint(
            "design_reference_id",
            "work_item_id",
            "page_id",
            "node_id",
            name="uq_design_link_anchor",
        ),
    )


class PreviewDeployment(db.Model):
    """An isolated, expiring non-production preview bound to immutable inputs."""

    __tablename__ = "preview_deployments"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mockup_artifact_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    mockup_version: Mapped[int] = mapped_column(Integer, nullable=False)
    mockup_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    change_set_id: Mapped[uuid_pk | None] = mapped_column(
        Uuid, ForeignKey("change_sets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    commit_sha: Mapped[str] = mapped_column(String(128), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False, default="preview")
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    access_policy: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    mockup_artifact = relationship("Artifact")
    change_set = relationship("ChangeSet")
    sessions = relationship(
        "AcceptanceSession", back_populates="preview", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (Index("ix_preview_deployments_project_status", "project_id", "status"),)


class AcceptanceSession(db.Model):
    """A human acceptance test session against one protected preview."""

    __tablename__ = "acceptance_sessions"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    preview_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("preview_deployments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    work_item_id: Mapped[uuid_pk | None] = mapped_column(
        Uuid, ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    scenario_guidance: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    criteria: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    completed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    preview = relationship("PreviewDeployment", back_populates="sessions")
    work_item = relationship("WorkItem")
    results = relationship(
        "AcceptanceResult", back_populates="session", cascade="all, delete-orphan", lazy="selectin"
    )
    defects = relationship("Defect", back_populates="session", lazy="selectin")


class Defect(db.Model):
    """Acceptance defect; closure is gated by regression evidence when required."""

    __tablename__ = "defects"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[uuid_pk | None] = mapped_column(
        Uuid, ForeignKey("acceptance_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    work_item_id: Mapped[uuid_pk | None] = mapped_column(
        Uuid, ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    reproduction_steps: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    expected: Mapped[str] = mapped_column(Text, nullable=False)
    actual: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    regression_test_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    regression_evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    session = relationship("AcceptanceSession", back_populates="defects")
    work_item = relationship("WorkItem")

    __table_args__ = (
        Index("ix_defects_project_status_severity", "project_id", "status", "severity"),
    )


class AcceptanceResult(db.Model):
    __tablename__ = "acceptance_results"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("acceptance_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    criterion_key: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    defect_id: Mapped[uuid_pk | None] = mapped_column(
        Uuid, ForeignKey("defects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recorded_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    session = relationship("AcceptanceSession", back_populates="results")
    defect = relationship("Defect")

    __table_args__ = (
        UniqueConstraint("session_id", "criterion_key", name="uq_acceptance_result_criterion"),
    )


class TraceLink(db.Model):
    __tablename__ = "trace_links"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    relation: Mapped[str] = mapped_column(String(32), nullable=False, default="satisfies")
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "source_type",
            "source_id",
            "target_type",
            "target_id",
            "relation",
            name="uq_trace_link",
        ),
        Index("ix_trace_links_source", "project_id", "source_type", "source_id"),
        Index("ix_trace_links_target", "project_id", "target_type", "target_id"),
    )


class AgentRun(db.Model):
    __tablename__ = "agent_runs"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_artifact_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    current_step: Mapped[str | None] = mapped_column(String(128), nullable=True)
    allowed_tools: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    writable_paths: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    environment: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    model_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    budget: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    pause_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    plan_artifact = relationship("Artifact")
    events = relationship(
        "AgentRunEvent",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentRunEvent.sequence",
        lazy="selectin",
    )
    checkpoints = relationship(
        "AgentCheckpoint",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentCheckpoint.sequence",
        lazy="selectin",
    )


class AgentRunEvent(db.Model):
    __tablename__ = "agent_run_events"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    run = relationship("AgentRun", back_populates="events")

    __table_args__ = (UniqueConstraint("run_id", "sequence", name="uq_agent_run_event_sequence"),)


class AgentCheckpoint(db.Model):
    __tablename__ = "agent_checkpoints"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    run = relationship("AgentRun", back_populates="checkpoints")

    __table_args__ = (UniqueConstraint("run_id", "sequence", name="uq_agent_checkpoint_sequence"),)


class ChangeSet(db.Model):
    __tablename__ = "change_sets"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    plan_artifact_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    branch: Mapped[str] = mapped_column(String(255), nullable=False)
    base_commit: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    diff_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    self_review: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    run = relationship("AgentRun")
    plan_artifact = relationship("Artifact")
    files = relationship(
        "ChangeSetFile",
        back_populates="change_set",
        cascade="all, delete-orphan",
        order_by="ChangeSetFile.path",
        lazy="selectin",
    )
    verifications = relationship(
        "VerificationRun",
        back_populates="change_set",
        cascade="all, delete-orphan",
        order_by="VerificationRun.created_at",
        lazy="selectin",
    )


class ChangeSetFile(db.Model):
    __tablename__ = "change_set_files"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    change_set_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("change_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    diff: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    change_set = relationship("ChangeSet", back_populates="files")

    __table_args__ = (UniqueConstraint("change_set_id", "path", name="uq_change_set_file_path"),)


class VerificationRun(db.Model):
    __tablename__ = "verification_runs"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    change_set_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("change_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    change_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    waiver_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    waiver_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    change_set = relationship("ChangeSet", back_populates="verifications")


class Release(db.Model):
    """Immutable release identity plus mutable readiness/package state."""

    __tablename__ = "releases"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    change_set_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("change_sets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(128), nullable=False)
    release_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    readiness: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    package: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    rollback: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    change_set = relationship("ChangeSet")
    readiness_checks = relationship(
        "ReleaseReadinessCheck",
        back_populates="release",
        cascade="all, delete-orphan",
        order_by="ReleaseReadinessCheck.created_at",
        lazy="selectin",
    )
    deployment_plans = relationship(
        "DeploymentPlan", back_populates="release", cascade="all, delete-orphan", lazy="selectin"
    )
    deployments = relationship(
        "Deployment", back_populates="release", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (UniqueConstraint("project_id", "version", name="uq_release_project_version"),)


class ReleaseReadinessCheck(db.Model):
    __tablename__ = "release_readiness_checks"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    release_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("releases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    release = relationship("Release", back_populates="readiness_checks")

    __table_args__ = (UniqueConstraint("release_id", "key", name="uq_release_readiness_key"),)


class DeploymentPlan(db.Model):
    __tablename__ = "deployment_plans"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    release_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("releases.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    release = relationship("Release", back_populates="deployment_plans")


class Deployment(db.Model):
    __tablename__ = "deployments"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    release_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("releases.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    deployment_plan_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("deployment_plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="webhook")
    provider_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    diagnostics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    health_checks: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    rollback: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    release = relationship("Release", back_populates="deployments")
    deployment_plan = relationship("DeploymentPlan")


class Approval(db.Model):
    __tablename__ = "approvals"

    id: Mapped[uuid_pk] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid_pk] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid_pk | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    artifact_type: Mapped[str] = mapped_column(String(48), nullable=False)
    artifact_id: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_version: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decider_id: Mapped[str] = mapped_column(String(255), nullable=False)
    decider_roles: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    author_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_approvals_artifact", "artifact_type", "artifact_id"),
        Index("ix_approvals_org_created", "organization_id", "created_at"),
    )


def register_audit_guards() -> None:
    from sqlalchemy import event as sa_event

    @sa_event.listens_for(AuditEvent, "before_update", propagate=True)
    def _block_update(mapper, connection, target):
        raise PermissionError("Audit events are append-only and cannot be updated")

    @sa_event.listens_for(AuditEvent, "before_delete", propagate=True)
    def _block_delete(mapper, connection, target):
        raise PermissionError("Audit events are append-only and cannot be deleted")


def register_immutability_guards() -> None:
    from sqlalchemy import event as sa_event
    from sqlalchemy import inspect as sa_inspect

    def make_pair(label: str):
        def block_update(mapper, connection, target):
            raise PermissionError(f"{label} are append-only and immutable")

        def block_delete(mapper, connection, target):
            raise PermissionError(f"{label} are append-only and immutable")

        return block_update, block_delete

    for model, label in (
        (RequirementBaselineVersion, "Requirement baseline versions"),
        (ArtifactVersion, "Artifact versions"),
        (ArchitectureDecisionRecord, "Architecture decision records"),
        (Approval, "Approval records"),
        (AgentRunEvent, "Agent run events"),
        (AgentCheckpoint, "Agent checkpoints"),
        (ChangeSetFile, "Change-set files"),
        (ProjectGateDecision, "Project gate decisions"),
        (ProjectGateHistory, "Project gate history entries"),
    ):
        update_guard, delete_guard = make_pair(label)
        sa_event.listens_for(model, "before_update", propagate=True)(update_guard)
        sa_event.listens_for(model, "before_delete", propagate=True)(delete_guard)

    def guard_release_identity(mapper, connection, target):
        state = sa_inspect(target)
        fields = ("project_id", "change_set_id", "version", "commit_sha", "content_hash")
        if any(state.attrs[field].history.has_changes() for field in fields):
            raise PermissionError("Release identity fields are immutable")

    def guard_deployment_plan_identity(mapper, connection, target):
        state = sa_inspect(target)
        fields = ("project_id", "release_id", "environment", "version", "content", "content_hash")
        if any(state.attrs[field].history.has_changes() for field in fields):
            raise PermissionError("Deployment plan identity fields are immutable")

    sa_event.listens_for(Release, "before_update", propagate=True)(guard_release_identity)
    sa_event.listens_for(DeploymentPlan, "before_update", propagate=True)(
        guard_deployment_plan_identity
    )
