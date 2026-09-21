import io
import tarfile
import uuid
from pathlib import Path

import pytest

from app.backup.service import (
    BACKUP_FORMAT,
    BackupError,
    _dump_value,
    create_backup,
    read_manifest,
    restore_backup,
)
from app.extensions import db
from app.models import AuditEvent, Organization, Project, Secret, WorkItem
from app.orgs.service import create_organization


def _seed(app):
    from app.auth.providers.local import LocalProvider

    org = create_organization("Backup Org", slug="backup")
    LocalProvider(org.slug).ensure_local_user(
        "admin@backup.local", "password123", "Backup Admin", ["organization_administrator"]
    )
    project = Project(
        organization_id=org.id,
        name="Pilot",
        key="pilot",
        description="pilot repo",
        default_branch="main",
    )
    secret = Secret(
        organization_id=org.id,
        name="OPENAI_API_KEY",
        encrypted_value="fernet:abc",
        secret_store="local",
        status="active",
    )
    db.session.add_all([project, secret])
    db.session.commit()
    from app.audit.service import record_audit

    record_audit(action="project.created", organization_id=org.id, target_id=project.id)
    record_audit(action="secret.created", organization_id=org.id, target_id=secret.id)
    return org, project, secret


def test_backup_manifest_and_tables(app, tmp_path):
    org, project, _ = _seed(app)
    archive = tmp_path / "backup.tar.gz"
    manifest = create_backup(archive, include_git_keys=False)

    assert archive.exists()
    assert manifest["format"] == BACKUP_FORMAT
    assert manifest["tables"]["organizations"] == 1
    assert manifest["tables"]["projects"] == 1
    assert manifest["tables"]["audit_events"] == 2

    inspected = read_manifest(archive)
    assert inspected["verified"] is True
    assert inspected["database"]["sha256"] == manifest["database"]["sha256"]

    with tarfile.open(archive, "r:gz") as tar:
        names = set(tar.getnames())
    assert {"manifest.json", "database.json"} <= names


def test_backup_serializes_custom_uuid_columns():
    column = WorkItem.__table__.c.source_analysis_id
    value = uuid.uuid4()
    assert _dump_value(value, column) == str(value)


def test_backup_restore_round_trip(app, tmp_path):
    org, project, secret = _seed(app)
    archive = tmp_path / "backup.tar.gz"
    create_backup(archive, include_git_keys=False)

    project_id = project.id
    secret_id = secret.id
    org_id = org.id
    project_name = project.name

    from app.audit.service import verify_chain

    assert verify_chain(org_id)["verified"] is True

    for table in reversed(db.metadata.sorted_tables):
        db.session.execute(table.delete())
    db.session.commit()
    assert Project.query.count() == 0

    result = restore_backup(archive, replace=True)
    assert result["restored"]["projects"] == 1
    assert result["restored"]["audit_events"] == 2

    restored = Project.query.filter_by(id=project_id).one()
    assert restored.name == project_name
    assert restored.organization_id == org_id
    assert Secret.query.filter_by(id=secret_id).one().name == "OPENAI_API_KEY"
    assert Organization.query.filter_by(id=org_id).one().slug == "backup"

    chain = verify_chain(org_id)
    assert chain["verified"] is True
    assert chain["verified_count"] == 2


def test_restore_refuses_non_empty_without_replace(app, tmp_path):
    _seed(app)
    archive = tmp_path / "backup.tar.gz"
    create_backup(archive, include_git_keys=False)

    with pytest.raises(BackupError):
        restore_backup(archive)

    assert Organization.query.count() == 1


def test_restore_dry_run_writes_nothing(app, tmp_path):
    _seed(app)
    archive = tmp_path / "backup.tar.gz"
    create_backup(archive, include_git_keys=False)
    before = AuditEvent.query.count()

    result = restore_backup(archive, dry_run=True)
    assert result["dry_run"] is True
    assert result["would_restore"]["organizations"] == 1
    assert AuditEvent.query.count() == before


def test_tampered_payload_is_rejected(app, tmp_path):
    _seed(app)
    archive = tmp_path / "backup.tar.gz"
    create_backup(archive, include_git_keys=False)

    tampered = tmp_path / "tampered.tar.gz"
    with tarfile.open(archive, "r:gz") as src, tarfile.open(tampered, "w:gz") as dst:
        for member in src.getmembers():
            data = src.extractfile(member).read() if member.isfile() else b""
            if member.name == "database.json":
                data = data.replace(b"Backup Org", b"Tampered!!")
            dst.addfile(member, io.BytesIO(data))

    with pytest.raises(BackupError, match="checksum"):
        read_manifest(tampered)
    with pytest.raises(BackupError, match="checksum"):
        restore_backup(tampered, replace=True)


def test_backup_includes_git_keys(app, tmp_path):
    _seed(app)
    key_dir = Path(app.config["GIT_KEY_DIR"])
    key_dir.mkdir(parents=True, exist_ok=True)
    (key_dir / "project_deploy_key").write_text("PRIVATE KEY")
    (key_dir / "project_deploy_key.pub").write_text("ssh-ed25519 AAAA")

    archive = tmp_path / "backup.tar.gz"
    manifest = create_backup(archive, include_git_keys=True)
    assert manifest["files"]["gitkeys"] == 2

    with tarfile.open(archive, "r:gz") as tar:
        assert "gitkeys/project_deploy_key" in tar.getnames()


def test_cli_create_and_verify(app, tmp_path):
    _seed(app)
    archive = tmp_path / "cli.tar.gz"
    runner = app.test_cli_runner()

    created = runner.invoke(args=["backup", "create", "-o", str(archive), "--no-include-git-keys"])
    assert created.exit_code == 0, created.output
    assert "Backup written" in created.output

    verified = runner.invoke(args=["backup", "verify", str(archive)])
    assert verified.exit_code == 0, verified.output
    assert "OK" in verified.output


def test_cli_restore_dry_run(app, tmp_path):
    _seed(app)
    archive = tmp_path / "cli.tar.gz"
    runner = app.test_cli_runner()
    runner.invoke(args=["backup", "create", "-o", str(archive), "--no-include-git-keys"])

    restored = runner.invoke(args=["backup", "restore", str(archive), "--dry-run"])
    assert restored.exit_code == 0, restored.output
    assert "Dry run" in restored.output
    assert Organization.query.count() == 1
