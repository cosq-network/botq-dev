"""Validate managed-inference and Phase 4 integration configuration safely.

The script reports missing configuration names, never prints secret values, and
does not make network calls. It is suitable for CI baseline checks and for a
deployment preflight before running a real provider deployment.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.security.network import validate_external_https_url


def _https(value: str) -> bool:
    try:
        validate_external_https_url(value)
    except ValueError:
        return False
    return True


def validate(
    environ: dict[str, str],
    *,
    require_phase3: bool = False,
    require_phase4: bool = False,
    require_phase5: bool = False,
):
    analysis = [
        item.strip().lower()
        for item in environ.get("REQUIREMENT_ANALYSIS_PROVIDER", "rules").split(",")
        if item.strip()
    ]
    implementation = [
        item.strip().lower()
        for item in environ.get("AGENT_IMPLEMENTATION_PROVIDER", "disabled").split(",")
        if item.strip()
    ]
    allowed = {"rules", "heroku", "runpod", "openai_compatible"}
    errors = []
    warnings = []

    if not analysis or any(item not in allowed for item in analysis):
        errors.append(
            "REQUIREMENT_ANALYSIS_PROVIDER must contain rules, heroku, runpod, or openai_compatible"
        )
    if not implementation or any(
        item not in {"disabled", "heroku", "runpod", "openai_compatible"} for item in implementation
    ):
        errors.append(
            "AGENT_IMPLEMENTATION_PROVIDER must contain disabled, heroku, runpod, or openai_compatible"
        )
    if require_phase3 and implementation == ["disabled"]:
        errors.append("Managed implementation requires AGENT_IMPLEMENTATION_PROVIDER")

    selected = set(analysis + implementation)
    if "heroku" in selected:
        for name in (
            "HEROKU_INFERENCE_BASE_URL",
            "HEROKU_INFERENCE_KEY",
            "HEROKU_INFERENCE_MODEL",
        ):
            if not environ.get(name):
                errors.append(f"missing {name}")
        if environ.get("HEROKU_INFERENCE_BASE_URL") and not _https(
            environ["HEROKU_INFERENCE_BASE_URL"]
        ):
            errors.append("HEROKU_INFERENCE_BASE_URL must be HTTPS")
    if "runpod" in selected:
        for name in ("RUNPOD_API_KEY", "RUNPOD_ENDPOINT_ID"):
            if not environ.get(name):
                errors.append(f"missing {name}")
        if environ.get("RUNPOD_INFERENCE_URL") and not _https(
            environ["RUNPOD_INFERENCE_URL"]
        ):
            errors.append("RUNPOD_INFERENCE_URL must be HTTPS")
    if "openai_compatible" in selected:
        for name in (
            "OPENAI_COMPATIBLE_BASE_URL",
            "OPENAI_COMPATIBLE_API_KEY",
            "OPENAI_COMPATIBLE_MODEL",
            "OPENAI_COMPATIBLE_MAX_TOKENS",
        ):
            if not environ.get(name):
                errors.append(f"missing {name}")
        if environ.get("OPENAI_COMPATIBLE_BASE_URL") and not _https(environ["OPENAI_COMPATIBLE_BASE_URL"]):
            errors.append("OPENAI_COMPATIBLE_BASE_URL must be HTTPS")
        if environ.get("OPENAI_COMPATIBLE_MAX_TOKENS"):
            try:
                if int(environ["OPENAI_COMPATIBLE_MAX_TOKENS"]) <= 0:
                    errors.append("OPENAI_COMPATIBLE_MAX_TOKENS must be positive")
            except ValueError:
                errors.append("OPENAI_COMPATIBLE_MAX_TOKENS must be an integer")

    if require_phase4:
        for name in (
            "PENPOT_API_BASE_URL",
            "PENPOT_API_TOKEN",
            "PREVIEW_DEPLOYMENT_URL",
            "PREVIEW_DEPLOYMENT_TOKEN",
        ):
            if not environ.get(name):
                errors.append(f"missing {name}")
        for name in ("PENPOT_API_BASE_URL", "PREVIEW_DEPLOYMENT_URL"):
            if environ.get(name) and not _https(environ[name]):
                errors.append(f"{name} must be HTTPS")
    elif not environ.get("PREVIEW_DEPLOYMENT_URL"):
        warnings.append(
            "PREVIEW_DEPLOYMENT_URL is not configured; preview URLs must be supplied manually"
        )

    if require_phase5:
        deployment_adapter = environ.get("DEPLOYMENT_ADAPTER", "webhook").strip().lower()
        if deployment_adapter == "local_compose":
            for name in (
                "LOCAL_COMPOSE_FILE",
                "LOCAL_COMPOSE_ROLLBACK_FILE",
                "LOCAL_DEPLOYMENT_HEALTH_URL",
            ):
                if not environ.get(name):
                    errors.append(f"missing {name} for local_compose deployment")
            if environ.get("LOCAL_DEPLOYMENT_HEALTH_URL") and urlparse(
                environ["LOCAL_DEPLOYMENT_HEALTH_URL"]
            ).scheme not in {"http", "https"}:
                errors.append("LOCAL_DEPLOYMENT_HEALTH_URL must be HTTP or HTTPS")
        elif deployment_adapter == "webhook":
            for name in ("DEPLOYMENT_URL", "DEPLOYMENT_TOKEN"):
                if not environ.get(name):
                    errors.append(f"missing {name}")
            for name in ("DEPLOYMENT_URL", "DEPLOYMENT_ROLLBACK_URL"):
                if environ.get(name) and not _https(environ[name]):
                    errors.append(f"{name} must be HTTPS")
        else:
            errors.append("DEPLOYMENT_ADAPTER must be webhook or local_compose")
    elif not environ.get("DEPLOYMENT_URL"):
        warnings.append(
            "DEPLOYMENT_URL is not configured; deployment execution remains disabled"
        )

    return {
        "passed": not errors,
        "analysis_providers": analysis,
        "implementation_providers": implementation,
        "errors": errors,
        "warnings": warnings,
        "secrets_checked": True,
        "secrets_present": {
            "openai_compatible_api_key": bool(environ.get("OPENAI_COMPATIBLE_API_KEY")),
            "heroku_inference_key": bool(environ.get("HEROKU_INFERENCE_KEY")),
            "runpod_api_key": bool(environ.get("RUNPOD_API_KEY")),
        },
        "network_probe": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-phase3", action="store_true")
    parser.add_argument("--require-phase4", action="store_true")
    parser.add_argument("--require-phase5", action="store_true")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "backend" / ".env",
        help="optional dotenv file to inspect without printing its values",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    # The application loads backend/.env, whereas this standalone script used
    # to inspect only the invoking shell.  Merge safely so shell-provided
    # deployment values take precedence and secret values are never rendered.
    env_file_values = (
        {key: value for key, value in dotenv_values(args.env_file).items() if value is not None}
        if args.env_file.is_file()
        else {}
    )
    effective_environ = {**env_file_values, **dict(os.environ)}
    report = validate(
        effective_environ,
        require_phase3=args.require_phase3,
        require_phase4=args.require_phase4,
        require_phase5=args.require_phase5,
    )
    report["env_file_loaded"] = args.env_file.is_file()
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            "PASS provider configuration baseline"
            if report["passed"]
            else "FAIL provider configuration baseline"
        )
        for item in report["errors"]:
            print(f"ERROR {item}")
        for item in report["warnings"]:
            print(f"WARN {item}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
