"""Create a deterministic, secret-free release evidence manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess  # nosec - fixed local evidence commands only.
from datetime import datetime, timezone
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True)
    parser.add_argument("--change-set-hash", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", default="botq-api:latest")
    parser.add_argument("--sbom", type=Path)
    parser.add_argument(
        "--skip-image",
        action="store_true",
        help="omit image inspection for dependency-only evidence; not valid for a release package",
    )
    args = parser.parse_args()
    files = [Path("backend/Dockerfile"), Path("backend/requirements.txt"), Path("backend/requirements-dev.txt")]
    sbom_path = args.sbom or args.output.with_name("sbom.json")
    try:
        sbom_process = subprocess.run(  # nosec - fixed executable and arguments.
            ["pip-audit", "-r", "backend/requirements.txt", "--format", "cyclonedx-json"],
            capture_output=True,
            text=True,
            check=True,
        )
        sbom = json.loads(sbom_process.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Unable to generate CycloneDX SBOM with pip-audit: {exc}") from exc
    sbom_path.parent.mkdir(parents=True, exist_ok=True)
    sbom_path.write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.skip_image:
        image_id = None
    else:
        try:
            image_id = subprocess.check_output(  # nosec - fixed docker inspect arguments.
                ["docker", "image", "inspect", args.image, "--format", "{{.Id}}"],
                text=True,
                stderr=subprocess.STDOUT,
            ).strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise SystemExit(f"Unable to inspect immutable Docker image {args.image}: {exc}") from exc
    manifest = {
        "format": "botq-release-evidence-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit_sha": args.commit,
        "change_set_hash": args.change_set_hash,
        "inputs": {str(path): digest(path) for path in files if path.is_file()},
        "sbom": {"path": str(sbom_path), "sha256": digest(sbom_path)},
        "image": {"reference": args.image, "immutable_id": image_id},
        "checksums": {str(path): digest(path) for path in [*files, sbom_path] if path.is_file()},
        "commands": ["pytest", "ruff", "bandit", "pip-audit", "docker build"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
