"""Exercise the local Compose deployment adapter and write evidence JSON."""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404 - script executes fixed docker compose argv.
from datetime import UTC, datetime
from pathlib import Path

from app.release.adapter import LocalComposeDeploymentAdapter


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compose-file", action="append", required=True)
    parser.add_argument("--rollback-compose-file", action="append", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--health-url", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--deployment-id", default="local-compose-evidence")
    parser.add_argument("--health-timeout", default="120")
    parser.add_argument("--keep-running", action="store_true")
    args = parser.parse_args()

    adapter = LocalComposeDeploymentAdapter(
        {
            "LOCAL_COMPOSE_FILE": args.compose_file,
            "LOCAL_COMPOSE_PROJECT": args.project,
            "LOCAL_DEPLOYMENT_HEALTH_URL": args.health_url,
            "LOCAL_DEPLOYMENT_HEALTH_TIMEOUT_SECONDS": args.health_timeout,
        }
    )
    manifest = {
        "deployment_id": args.deployment_id,
        "environment": "local-pilot",
        "release": {"version": "local-compose-evidence"},
        "rollback": {"compose_files": args.rollback_compose_file},
    }

    evidence = {
        "generated_at": datetime.now(UTC).isoformat(),
        "compose_files": args.compose_file,
        "rollback_compose_files": args.rollback_compose_file,
        "project": args.project,
        "health_url": args.health_url,
        "deployment": adapter.provision(manifest).__dict__,
        "rollback": adapter.rollback(manifest).__dict__,
    }

    if not args.keep_running:
        down = _compose_command(args.compose_file, args.project, "down", "-v", "--remove-orphans")
        completed = subprocess.run(  # nosec B603 - fixed docker compose teardown argv.
            down,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        evidence["teardown"] = {
            "command": down,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-2000:],
            "stderr": completed.stderr[-2000:],
        }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    ok = (
        evidence["deployment"]["status"] == "healthy"
        and evidence["rollback"]["status"] == "healthy"
        and evidence.get("teardown", {}).get("returncode", 0) == 0
    )
    print(json.dumps({"ok": ok, "output": str(output)}, sort_keys=True))
    return 0 if ok else 1


def _compose_command(compose_files: list[str], project: str, *args: str) -> list[str]:
    command = ["docker", "compose"]
    for compose_file in compose_files:
        command.extend(["-f", compose_file])
    command.extend(["-p", project, *args])
    return command


if __name__ == "__main__":
    raise SystemExit(main())
