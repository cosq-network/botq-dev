"""Fail CI when a published API operation loses its typed request contract."""

from __future__ import annotations

import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "contract-check-secret")
os.environ.setdefault("AUDIT_SECRET", "contract-check-audit")
os.environ.setdefault("BOOTSTRAP_TOKEN", "contract-check-bootstrap")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app import create_app  # noqa: E402
from app.api.dtos import request_dto_for  # noqa: E402


def main() -> int:
    app = create_app()
    with app.test_client() as client:
        document = client.get("/openapi.json").get_json()
    operation_ids = []
    for path, operations in document["paths"].items():
        for method, operation in operations.items():
            if method not in {"post", "put", "patch"}:
                continue
            operation_ids.append(operation["operationId"])
            body = operation.get("requestBody", {}).get("content", {}).get("application/json", {})
            if "$ref" not in body.get("schema", {}) and not body.get("schema", {}).get("properties"):
                raise SystemExit(f"{method.upper()} {path} has no typed request schema")
    if len(operation_ids) != len(set(operation_ids)):
        raise SystemExit("OpenAPI operationId values must be unique")
    if len(document["paths"]) < 70:
        raise SystemExit("OpenAPI contract is unexpectedly incomplete")
    print(f"validated {len(document['paths'])} paths and {len(operation_ids)} typed mutating operations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
