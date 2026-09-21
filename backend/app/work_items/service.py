"""Work Item hierarchy (REQ-REQ-02/06).

Epics -> Features -> Stories -> Tasks / Test Cases. Every item carries a
project-unique identifier (`PROJECTKEY-<n>`), acceptance criteria, priority,
risk and status, and must either trace to a requirement baseline or be flagged
as a derived technical item. Dependencies are directed (item *depends on*
predecessor) and circular dependencies are rejected.
"""

from sqlalchemy import func

from ..errors import ConflictError, NotFoundError, ValidationError
from ..extensions import db
from ..models import RequirementBaseline, WorkItem
from ..utils import new_uuid

# Lower rank == higher in the hierarchy. A child must be strictly lower.
KIND_RANK = {"epic": 0, "feature": 1, "story": 2, "task": 3, "test_case": 3}
KINDS = set(KIND_RANK)
PRIORITIES = {"critical", "high", "medium", "low"}
RISKS = {"low", "medium", "high"}
STATUSES = {"draft", "ready", "in_progress", "blocked", "in_review", "done", "cancelled"}
BLOCKING_STATUSES = {"blocked"}


def validate_enum(value, allowed, field):
    if value not in allowed:
        raise ValidationError(f"{field} must be one of: {', '.join(sorted(allowed))}")
    return value


def next_number(project_id) -> int:
    current = (
        db.session.query(func.max(WorkItem.number))
        .filter(WorkItem.project_id == project_id)
        .scalar()
    )
    return (current or 0) + 1


def validate_parent(kind: str, parent: WorkItem | None) -> None:
    """Enforce the Epic/Feature/Story/Task/Test Case hierarchy."""
    if kind == "epic":
        if parent is not None:
            raise ValidationError("An epic must be a root item with no parent")
        return
    if parent is None:
        raise ValidationError(f"A {kind} must belong to a parent item")
    if KIND_RANK[parent.kind] >= KIND_RANK[kind]:
        raise ValidationError(
            f"A {kind} cannot be a child of a {parent.kind}; "
            "items must nest Epic > Feature > Story > Task/Test Case"
        )


def validate_traceability(source_baseline_id, is_derived: bool, organization_id, project_id):
    if is_derived or source_baseline_id is not None:
        if source_baseline_id is not None:
            baseline = RequirementBaseline.query.filter_by(
                id=source_baseline_id, organization_id=organization_id, project_id=project_id
            ).first()
            if baseline is None:
                raise ValidationError("source_baseline_id does not reference a valid baseline")
        return
    raise ValidationError(
        "A work item must trace to a requirement baseline (source_baseline_id) or be marked derived"
    )


def _descendants(item: WorkItem) -> set:
    """All descendant ids reachable via the children adjacency."""
    seen: set = set()
    stack = [item]
    while stack:
        node = stack.pop()
        for child in node.children:
            if child.id not in seen:
                seen.add(child.id)
                stack.append(child)
    return seen


def _upstream_closure(start: WorkItem) -> set:
    """All items reachable by following *depends on* edges from start."""
    seen: set = set()
    stack = [start]
    while stack:
        node = stack.pop()
        if node.id in seen:
            continue
        seen.add(node.id)
        for dep in node.dependencies:
            stack.append(dep)
    return seen


def add_dependency(item: WorkItem, depends_on: WorkItem) -> None:
    if item.id == depends_on.id:
        raise ConflictError("A work item cannot depend on itself", code="circular_dependency")
    if (
        item.project_id != depends_on.project_id
        or item.organization_id != depends_on.organization_id
    ):
        raise ValidationError("Dependencies must be within the same project")
    if depends_on in item.dependencies:
        return
    # A cycle exists if the target already depends (transitively) on the source.
    upstream = _upstream_closure(depends_on)
    if item.id in upstream:
        raise ConflictError(
            "This dependency would create a circular chain",
            code="circular_dependency",
        )
    item.dependencies.append(depends_on)
    db.session.commit()


def validate_parent_change(item: WorkItem, new_parent: WorkItem | None) -> None:
    validate_parent(item.kind, new_parent)
    if new_parent is None:
        return
    if new_parent.id == item.id:
        raise ConflictError("A work item cannot be its own parent", code="circular_hierarchy")
    if new_parent.id in _descendants(item):
        raise ConflictError(
            "Reparenting would create a circular hierarchy",
            code="circular_hierarchy",
        )


def serialize(item: WorkItem, *, include_children: bool = False) -> dict:
    payload = {
        "id": str(item.id),
        "project_id": str(item.project_id),
        "code": item.code,
        "number": item.number,
        "kind": item.kind,
        "parent_id": str(item.parent_id) if item.parent_id else None,
        "title": item.title,
        "description": item.description,
        "acceptance_criteria": item.acceptance_criteria or [],
        "priority": item.priority,
        "risk": item.risk,
        "status": item.status,
        "owner_id": item.owner_id,
        "release_target": item.release_target,
        "estimate": item.estimate,
        "source_baseline_id": str(item.source_baseline_id) if item.source_baseline_id else None,
        "source_refs": item.source_refs or [],
        "is_derived": item.is_derived,
        "dependencies": sorted(dep.code for dep in item.dependencies),
        "dependents": sorted(dep.code for dep in item.dependents),
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }
    if include_children:
        payload["children_count"] = len(item.children)
    return payload


def build_tree(items: list[WorkItem]) -> list[dict]:
    by_id = {item.id: serialize(item, include_children=True) for item in items}
    for item in items:
        by_id[item.id]["children"] = []
    roots: list[dict] = []
    for item in items:
        node = by_id[item.id]
        if item.parent_id and item.parent_id in by_id:
            by_id[item.parent_id]["children"].append(node)
        else:
            roots.append(node)
    return roots


def get_owned_work_item(work_item_id, organization_id) -> WorkItem:
    item = WorkItem.query.filter_by(id=work_item_id, organization_id=organization_id).first()
    if item is None:
        raise NotFoundError("Work item not found")
    return item


def new_work_item(**kwargs) -> WorkItem:
    return WorkItem(id=new_uuid(), **kwargs)
