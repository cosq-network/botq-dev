"""Run repository-side security baseline checks without network access."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def validate(root: Path) -> dict:
    backend = root / "backend"
    sys.path.insert(0, str(backend))
    from cryptography.fernet import Fernet

    from app import create_app
    from app.config import Config

    class SecurityConfig(Config):
        ENVIRONMENT = "production"
        SECRET_KEY = "security-baseline-secret"
        AUDIT_SECRET = "security-baseline-audit-secret"
        SECRET_ENCRYPTION_KEY = Fernet.generate_key().decode()
        BOOTSTRAP_ENABLED = False
        SQLALCHEMY_DATABASE_URI = "sqlite://"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        TESTING = True
        RATE_LIMIT_ENABLED = True
        RATE_LIMIT_BACKEND = "redis"
        REDIS_URL = "redis://security-baseline.invalid:6379/0"
        SESSION_COOKIE_SECURE = True

    app = create_app(SecurityConfig)
    client = app.test_client()
    checks = {}
    checks["session:secure_cookie"] = app.config.get("SESSION_COOKIE_SECURE") is True
    checks["session:http_only"] = app.config.get("SESSION_COOKIE_HTTPONLY") is True
    checks["session:same_site"] = app.config.get("SESSION_COOKIE_SAMESITE") == "Lax"
    for path in ("/", "/workbench", "/health/live"):
        response = client.get(path)
        headers = response.headers
        checks[f"{path}:successful"] = response.status_code == 200
        checks[f"{path}:content_type"] = (
            headers.get("X-Content-Type-Options") == "nosniff"
        )
        checks[f"{path}:frame_protection"] = headers.get("X-Frame-Options") == "DENY"
        checks[f"{path}:referrer_policy"] = (
            headers.get("Referrer-Policy") == "no-referrer"
        )
        checks[f"{path}:csp"] = "object-src 'none'" in headers.get(
            "Content-Security-Policy", ""
        ) and "unsafe-inline" not in headers.get("Content-Security-Policy", "")
        checks[f"{path}:hsts"] = "max-age=31536000" in headers.get(
            "Strict-Transport-Security", ""
        )

    template_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (backend / "app/templates").glob("*.html")
    )
    checks["templates:no_inline_styles"] = "<style" not in template_text.lower()
    checks["templates:no_inline_scripts"] = not bool(
        re.search(r"<script(?![^>]*\bsrc=)[^>]*>", template_text, re.IGNORECASE)
    )
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "network_probe": False,
        "manual_review_required": True,
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    report = validate(root)
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for name, passed in report["checks"].items():
            print(f"{'PASS' if passed else 'FAIL'} {name}")
        print("Manual security review remains required.")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
