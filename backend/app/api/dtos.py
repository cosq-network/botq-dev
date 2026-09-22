"""Typed request DTO boundary for the Flask controllers.

The legacy controllers currently consume dictionaries. DTOs are generated from
the fields and coercions used by each controller, then applied before handler
execution. This gives callers a typed, discoverable contract while preserving
the controller-specific lifecycle and authorization validation already present.
"""

from __future__ import annotations

import inspect
import re
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, create_model

from .contracts import EXPLICIT_FIELDS

_KEY_RE = re.compile(
    r"(?:payload|data|body|updates|supplied|content)\s*(?:\.get\(\s*|\[\s*)(['\"])([^'\"]+)\1"
)
_DIRECT_ACCESS_RE = re.compile(r"(?:payload|data|body|updates|supplied|content)\s*\[\s*(['\"])([^'\"]+)\1\s*\]")
_UUID_FIELDS = re.compile(r"(?:_uuid|UUID)\([^\n]*?(?:payload|data|body|updates|supplied|content).*?['\"]([^'\"]+)['\"]")
_LIST_FIELDS = re.compile(r"(?:_strings|_string_list|_clean_str_list|_paths)\([^\n]*?(?:payload|data|body|updates|supplied|content)\.get\(\s*['\"]([^'\"]+)['\"]")
_BOOL_FIELDS = re.compile(r"payload\.get\(\s*['\"]([^'\"]+)['\"]\s*(?:,[^)]*)?\)\s*(?:is|==)\s*(?:not\s+)?(?:True|False)")
_INT_FIELDS = re.compile(r"int\(payload\.get\(\s*['\"]([^'\"]+)['\"]")


def request_dto_for(endpoint: str, view) -> type:
    """Build the stable DTO class associated with one controller endpoint."""
    function = inspect.unwrap(view) if view else None
    source = ""
    if function:
        try:
            source = inspect.getsource(function)
        except (OSError, TypeError):
            pass
    fields = EXPLICIT_FIELDS.get(endpoint, _field_types(source))
    name = _model_name(endpoint)
    annotations = {field: field_type | None for field, field_type in fields.items()}
    defaults = {field: None for field in fields}
    if not fields and endpoint not in EXPLICIT_FIELDS:
        annotations = {"payload": dict[str, Any]}
        defaults = {"payload": None}
    return create_model(
        name,
        __config__=ConfigDict(
            extra="allow",
            str_strip_whitespace=False,
            populate_by_name=True,
        ),
        __base__=TypedRequestDTO,
        **{
            field: (annotations[field], defaults[field])
            for field in annotations
        },
    )


class TypedRequestDTO(BaseModel):
    """Marker base used by generated request DTOs."""


def _field_types(source: str) -> dict[str, type]:
    fields = {match.group(2): str for match in _KEY_RE.finditer(source)}
    for field in _UUID_FIELDS.findall(source):
        fields[field] = UUID
    for field in _LIST_FIELDS.findall(source):
        fields[field] = list[str]
    for field in _BOOL_FIELDS.findall(source):
        fields[field] = bool
    for field in _INT_FIELDS.findall(source):
        fields[field] = int
    # A few controllers intentionally accept structured domain payloads. The
    # source-based discovery above cannot reliably infer their types across
    # multiline expressions, so keep these contracts explicit at the DTO
    # boundary instead of coercing valid JSON into strings.
    if "normalize_content(" in source and "content" in fields:
        fields["content"] = dict[str, Any]
    if "_validate_plan_content(" in source and "content" in fields:
        fields["content"] = dict[str, Any]
    if "_clean_str_list(" in source:
        for field in ("acceptance_criteria", "source_refs"):
            if field in fields:
                fields[field] = list[str]
    if "is_derived" in fields and (
        'payload.get("is_derived"' in source or "payload.get('is_derived'" in source
    ):
        fields["is_derived"] = bool
    if "_resolve_roles(" in source and "roles" in fields:
        fields["roles"] = list[str]
    if "_criteria(" in source and "criteria" in fields:
        fields["criteria"] = list[dict[str, Any]]
    if "regression_evidence" in fields and "regression_evidence" in source:
        fields["regression_evidence"] = dict[str, Any]
    if "enforce_project_responsibilities" in fields:
        fields["enforce_project_responsibilities"] = bool
    # Structured fields are intentionally broad at this boundary because the
    # controller owns their domain-specific validation and normalization.
    for field in fields:
        if re.search(rf"payload\.get\(\s*['\"]{re.escape(field)}['\"]\s*\)\s*or\s*\{{", source):
            fields[field] = dict[str, Any]
    return fields


def _model_name(endpoint: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", endpoint)
    return "".join(word.capitalize() for word in words) + "Request"


def dto_schema(model: type) -> dict:
    schema = model.model_json_schema()
    schema.pop("title", None)
    return schema
