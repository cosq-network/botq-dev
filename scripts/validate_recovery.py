"""Verify a backup and run a non-destructive restore compatibility drill."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REQUIRED_TABLES = {
    "organizations",
    "projects",
    "audit_events",
    "approvals",
    "artifacts",
}


def validate(root: Path, archive: Path) -> dict:
    sys.path.insert(0, str(root / "backend"))
    from app import create_app
    from app.backup.service import read_manifest, restore_backup
    from app.config import Config

    manifest = read_manifest(archive)
    tables = set(manifest.get("tables", {}))
    report = {
        "archive": str(archive.resolve()),
        "checksum_verified": manifest.get("verified", False),
        "format": manifest.get("format"),
        "required_tables_present": bool(REQUIRED_TABLES <= tables),
        "missing_required_tables": sorted(REQUIRED_TABLES - tables),
    }

    class RecoveryConfig(Config):
        SQLALCHEMY_DATABASE_URI = "sqlite://"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        SECRET_KEY = "recovery-drill-secret"
        AUDIT_SECRET = "recovery-drill-audit-secret"
        TESTING = True

    app = create_app(RecoveryConfig)
    with app.app_context():
        from app.extensions import db

        db.create_all()
        dry_run = restore_backup(archive, dry_run=True)
        report["dry_run"] = {
            "would_restore_rows": sum(dry_run["would_restore"].values()),
            "existing_rows": sum(dry_run["existing"].values()),
        }
        db.drop_all()
    report["passed"] = bool(
        report["checksum_verified"]
        and report["format"] == "botq-backup"
        and not report["missing_required_tables"]
    )
    report["destructive_restore_performed"] = False
    return report


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    try:
        report = validate(root, args.archive)
    except (OSError, ValueError, RuntimeError) as exc:
        report = {"passed": False, "error": type(exc).__name__, "detail": str(exc)}
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            "PASS recovery compatibility drill"
            if report["passed"]
            else "FAIL recovery compatibility drill"
        )
        if report.get("error"):
            print(f"ERROR {report['error']}: {report['detail']}")
        print("No destructive restore was performed.")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
