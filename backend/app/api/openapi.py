"""OpenAPI 3 generation and Swagger UI endpoints.

The API predates a schema library and its controllers intentionally accept
JSON dictionaries. This module keeps the source of truth in Flask's route
map, while extracting the request keys used by each controller so the
published contract stays useful as endpoints evolve.
"""

from __future__ import annotations

import inspect
import re

from flask import Blueprint, current_app, jsonify, make_response

from . import PUBLIC_ENDPOINTS
from .dtos import dto_schema, request_dto_for
from .response_contracts import DOMAIN_SCHEMAS, operation_response_schema

docs_bp = Blueprint("docs", __name__)

_PATH_PARAMETER_RE = re.compile(r"<(?:(?P<converter>[a-zA-Z_]+):)?(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)>")
_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


@docs_bp.get("/openapi.json")
def openapi_json():
    """Return the generated OpenAPI 3 contract."""
    return jsonify(build_openapi_spec(current_app))


@docs_bp.get("/docs")
@docs_bp.get("/docs/")
def swagger_ui():
    """Serve the interactive Swagger UI shell."""
    html = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>botq API documentation</title>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script src="/static/swagger-ui-init.js"></script>
  </body>
</html>"""
    return make_response(html)


def build_openapi_spec(app) -> dict:
    paths: dict[str, dict] = {}
    request_schemas: dict[str, dict] = {}
    response_schemas: dict[str, dict] = {}
    for rule in sorted(app.url_map.iter_rules(), key=lambda item: item.rule):
        methods = sorted(_HTTP_METHODS.intersection(rule.methods or set()))
        if not methods or rule.endpoint.startswith("static"):
            continue
        if rule.rule.startswith("/docs") or rule.rule == "/openapi.json":
            continue
        path = _openapi_path(rule.rule)
        view = app.view_functions.get(rule.endpoint)
        for method in methods:
            operation = _operation(app, rule, view, method)
            response_name, response_schema = operation_response_schema(rule.endpoint, rule.rule, method)
            operation["responses"]["200"] = _response("Successful response", response_name)
            response_schemas[response_name] = response_schema
            if method in {"POST", "PUT", "PATCH"}:
                model = request_dto_for(rule.endpoint, view)
                request_schemas[model.__name__] = dto_schema(model)
            paths.setdefault(path, {})[method.lower()] = operation

    return {
        "openapi": "3.0.3",
        "info": {
            "title": f"{app.config.get('APP_NAME', 'botq')} API",
            "version": "0.1.0",
            "description": (
                "Human-supervised AI software delivery control-plane API. "
                "State-changing operations remain subject to authorization, "
                "approval, lifecycle, and audit policies."
            ),
        },
        "servers": [{"url": "/", "description": "Current server"}],
        "tags": _tags(paths),
        "paths": paths,
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "opaque token",
                    "description": "Organization-scoped bearer token from the local login endpoint.",
                },
                "bootstrapToken": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-Bootstrap-Token",
                    "description": "Development/bootstrap-only organization management token.",
                },
            },
            "schemas": {
                "ApiResponse": {
                    "type": "object",
                    "required": ["ok", "correlation_id"],
                    "properties": {
                        "ok": {"type": "boolean", "example": True},
                        "correlation_id": {"type": "string", "format": "uuid"},
                        "message": {"type": "string"},
                        "data": {},
                    },
                },
                "ErrorResponse": {
                    "type": "object",
                    "required": ["ok", "correlation_id", "error"],
                    "properties": {
                        "ok": {"type": "boolean", "example": False},
                        "correlation_id": {"type": "string", "format": "uuid"},
                        "error": {
                            "type": "object",
                            "required": ["code", "message"],
                            "properties": {
                                "code": {"type": "string"},
                                "message": {"type": "string"},
                                "details": {},
                            },
                        },
                    },
                },
                **request_schemas,
                **DOMAIN_SCHEMAS,
                **response_schemas,
            },
        },
    }


def _operation(app, rule, view, method: str) -> dict:
    endpoint = rule.endpoint
    function = inspect.unwrap(view) if view else None
    summary = _summary(endpoint, method)
    operation = {
        "operationId": endpoint.replace(".", "_"),
        "summary": summary,
        "description": (inspect.getdoc(function) or summary) if function else summary,
        "tags": [_tag_for(rule.rule)],
        "parameters": _path_parameters(rule.rule),
        "responses": {
            "200": _response("Successful response"),
            "400": _response("Validation or request error", "ErrorResponse"),
            "401": _response("Authentication required", "ErrorResponse"),
            "403": _response("Authorization failed", "ErrorResponse"),
            "404": _response("Resource not found", "ErrorResponse"),
            "422": _response("Validation failed", "ErrorResponse"),
        },
    }
    if method in {"POST", "PUT", "PATCH"}:
        model = request_dto_for(endpoint, view)
        operation["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": f"#/components/schemas/{model.__name__}"}
                }
            },
        }

    if endpoint in PUBLIC_ENDPOINTS:
        if endpoint.endswith("login_local"):
            operation["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": _login_schema()}},
            }
        elif endpoint in {"api.orgs.create_org", "api.orgs.list_orgs"}:
            operation["security"] = [{"bootstrapToken": []}]
    elif rule.rule.startswith("/api/"):
        operation["security"] = [{"bearerAuth": []}]
    return operation


def _login_schema() -> dict:
    return {
        "type": "object",
        "required": ["email", "password"],
        "properties": {
            "organization": {"type": "string", "description": "Organization slug."},
            "email": {"type": "string", "format": "email"},
            "password": {"type": "string", "format": "password"},
        },
    }


def _path_parameters(rule: str) -> list[dict]:
    result = []
    for match in _PATH_PARAMETER_RE.finditer(rule):
        converter = match.group("converter") or "string"
        schema = {"type": "integer"} if converter == "int" else {"type": "string"}
        if converter == "uuid":
            schema["format"] = "uuid"
        result.append(
            {
                "name": match.group("name"),
                "in": "path",
                "required": True,
                "schema": schema,
            }
        )
    return result


def _response(description: str, schema: str = "ApiResponse") -> dict:
    return {
        "description": description,
        "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{schema}"}}},
    }


def _openapi_path(rule: str) -> str:
    return _PATH_PARAMETER_RE.sub(lambda match: "{" + match.group("name") + "}", rule)


def _tag_for(rule: str) -> str:
    parts = [part for part in rule.split("/") if part]
    if parts and parts[0] == "api":
        parts = parts[2:]
    return (parts[0] if parts else "system").replace("-", " ").title()


def _tags(paths: dict) -> list[dict]:
    names = sorted({operation["tags"][0] for path in paths.values() for operation in path.values()})
    return [{"name": name} for name in names]


def _summary(endpoint: str, method: str) -> str:
    name = endpoint.rsplit(".", 1)[-1].replace("_", " ")
    return f"{method.title()} {name}"
