"""Close project gates through the public API using an evidence manifest.

This client does not create evidence. It submits evidence supplied by a manifest,
evaluates each gate, records explicit API automation approval decisions, and
closes gates sequentially. Use --synthetic-evidence only for local API contract
testing; do not use it as pilot or production evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests


class Api:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token

    @classmethod
    def login(cls, base_url: str, organization: str, email: str, password: str) -> Api:
        response = requests.post(
            f"{base_url.rstrip('/')}/api/v1/auth/login",
            json={"organization": organization, "email": email, "password": password},
            timeout=30,
        )
        _check(response, "login")
        return cls(base_url, response.json()["data"]["token"])

    def request(self, method: str, path: str, *, expected: int = 200, **kwargs) -> Any:
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {self.token}"
        response = requests.request(
            method,
            f"{self.base_url}{path}",
            headers=headers,
            timeout=180,
            **kwargs,
        )
        _check(response, path, expected)
        body = response.json()
        return body.get("data")


def _check(response: requests.Response, action: str, expected: int = 200) -> None:
    if response.status_code != expected:
        raise RuntimeError(
            f"{action}: expected HTTP {expected}, got {response.status_code}: {response.text[:1000]}"
        )


def _load_manifest(path: Path | None) -> dict:
    if path is None:
        return {"gates": {}}
    with path.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("gates"), dict):
        raise TypeError("evidence manifest must contain an object field named 'gates'")
    return manifest


def _evidence_for(manifest: dict, gate_number: int, key: str, synthetic: bool) -> dict:
    gate = manifest.get("gates", {}).get(str(gate_number), {})
    checks = gate.get("checks", gate) if isinstance(gate, dict) else {}
    item = checks.get(key) if isinstance(checks, dict) else None
    if item is None and synthetic:
        evidence = {"gate": gate_number, "check": key, "result": "passed", "source": "synthetic"}
        return {
            "key": key,
            "status": "passed",
            "source": "synthetic-api-contract",
            "command": f"synthetic verify {key}",
            "content_hash": _hash(evidence),
            "evidence": evidence,
        }
    if not isinstance(item, dict):
        raise TypeError(f"missing evidence for gate {gate_number} check '{key}'")
    payload = {**item, "key": key}
    payload.setdefault("status", "passed")
    payload.setdefault("source", item.get("evidence", {}).get("source", "manifest"))
    payload.setdefault("content_hash", _hash(item))
    payload.setdefault("evidence", item.get("evidence", item))
    return payload


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def run(args: argparse.Namespace) -> dict:
    admin = Api.login(args.base_url, args.organization, args.admin_email, args.admin_password)
    automation = Api.login(
        args.base_url,
        args.organization,
        args.automation_email,
        args.automation_password,
    )
    manifest = _load_manifest(args.evidence_manifest)

    policy = admin.request(
        "PATCH",
        f"/api/v1/projects/{args.project_id}/gate-policy",
        json={
            "approval_mode": "api_automation",
            "require_gate_decisions": True,
            "require_project_responsibility_assignment": args.require_project_responsibility_assignment,
            "allow_waivers": True,
            "require_previous_gate_closed": True,
            "auto_sync_evidence": True,
        },
    )

    closed = []
    for gate_number in range(1, 8):
        base = f"/api/v1/projects/{args.project_id}/gates/{gate_number}"
        admin.request("POST", f"{base}/sync")
        gate = admin.request("GET", base)
        existing = {item["key"]: item["status"] for item in gate["checks"]}
        for key in gate["required_evidence"]:
            if existing.get(key) in {"passed", "waived", "not_applicable"}:
                continue
            payload = _evidence_for(manifest, gate_number, key, args.synthetic_evidence)
            admin.request(
                "POST",
                f"{base}/evidence",
                expected=201,
                headers={"Idempotency-Key": f"{args.run_id}-gate-{gate_number}-{key}"},
                json=payload,
            )
        evaluated = admin.request("POST", f"{base}/evaluate")
        if evaluated["blocking_checks"]:
            raise RuntimeError(
                f"gate {gate_number} is blocked: {json.dumps(evaluated['blocking_checks'])}"
            )
        automation.request(
            "POST",
            f"{base}/auto-approve",
            expected=201,
            json={"idempotency_key": f"{args.run_id}-gate-{gate_number}-approval"},
        )
        closed_gate = automation.request("POST", f"{base}/close")
        closed.append(closed_gate["number"])

    summary = admin.request("GET", f"/api/v1/projects/{args.project_id}/gates/summary")
    return {"policy": policy, "closed_gates": closed, "summary": summary}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("BOTQ_URL", "http://127.0.0.1:8886"))
    parser.add_argument("--organization", default=os.environ.get("BOTQ_ORGANIZATION", "pilot"))
    parser.add_argument("--project-id", default=os.environ.get("BOTQ_PROJECT_ID"), required=False)
    parser.add_argument("--admin-email", default=os.environ.get("BOTQ_ADMIN_EMAIL"))
    parser.add_argument("--admin-password", default=os.environ.get("BOTQ_ADMIN_PASSWORD"))
    parser.add_argument("--automation-email", default=os.environ.get("BOTQ_AUTOMATION_EMAIL"))
    parser.add_argument("--automation-password", default=os.environ.get("BOTQ_AUTOMATION_PASSWORD"))
    parser.add_argument("--evidence-manifest", type=Path)
    parser.add_argument("--synthetic-evidence", action="store_true")
    responsibility = parser.add_mutually_exclusive_group()
    responsibility.add_argument(
        "--require-project-responsibility-assignment",
        dest="require_project_responsibility_assignment",
        action="store_true",
        help="Require active project responsibility assignments (the secure default).",
    )
    responsibility.add_argument(
        "--allow-unassigned-responsibilities",
        dest="require_project_responsibility_assignment",
        action="store_false",
        help="Allow unassigned automation responsibilities for local contract testing only.",
    )
    parser.set_defaults(require_project_responsibility_assignment=True)
    parser.add_argument("--run-id", default=os.environ.get("BOTQ_GATE_RUN_ID", "api-gate-run"))
    args = parser.parse_args()
    missing = [
        name
        for name in ("project_id", "admin_email", "admin_password", "automation_email", "automation_password")
        if not getattr(args, name)
    ]
    if missing:
        parser.error("missing required values: " + ", ".join(missing))
    if not args.evidence_manifest and not args.synthetic_evidence:
        parser.error("--evidence-manifest is required unless --synthetic-evidence is set")
    try:
        report = run(args)
    except (OSError, RuntimeError, TypeError, requests.RequestException) as exc:
        print(f"api gate lifecycle failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
