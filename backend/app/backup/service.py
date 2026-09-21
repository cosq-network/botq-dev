"""Backup and restore baseline (REQ-INF-07).

A backup is a portable ``.tar.gz`` archive containing:

* ``manifest.json`` - format/version, creation time, per-table counts and the
  SHA-256 of the database payload (integrity check).
* ``database.json`` - a logical dump of every table (rows ordered for
  referential integrity, with ``audit_events`` kept in chain order so the
  tamper-evident chain still verifies after a restore).
* ``gitkeys/`` - per-project SSH deploy keys (optional).
* ``workspaces/`` - sandbox workspaces (optional, opt-in).

The dump is database-agnostic, so a backup taken from SQLite can be restored
into PostgreSQL and vice versa. Restores are explicit and destructive by
design: the target must be empty unless ``replace=True`` is passed, and the
payload checksum is verified before anything is written.
"""

import base64
import hashlib
import io
import json
import tarfile
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import DateTime, LargeBinary, Uuid, func, select

from ..extensions import db
from ..utils import utcnow

BACKUP_FORMAT = "botq-backup"
BACKUP_VERSION = 1
MANIFEST_NAME = "manifest.json"
DATABASE_NAME = "database.json"
GITKEYS_PREFIX = "gitkeys"
WORKSPACES_PREFIX = "workspaces"
KEY_FILE_MODE = 0o600


class BackupError(ValueError):
    """Raised when a backup cannot be created, read or restored."""


def _ordered_tables():
    return [table for table in db.metadata.sorted_tables if table.name != "alembic_version"]


def _dump_value(value, column):
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    column_type = column.type
    if isinstance(column_type, Uuid):
        return str(value)
    if isinstance(column_type, DateTime):
        return value.isoformat()
    if isinstance(column_type, LargeBinary):
        return base64.b64encode(value).decode("ascii")
    return value


def _load_value(value, column):
    if value is None:
        return None
    column_type = column.type
    if isinstance(column_type, Uuid):
        return uuid.UUID(str(value))
    if isinstance(column_type, DateTime):
        return datetime.fromisoformat(value)
    if isinstance(column_type, LargeBinary):
        return base64.b64decode(value)
    return value


def _dump_database() -> dict:
    database = {"tables": {}}
    for table in _ordered_tables():
        statement = select(table)
        if table.name == "audit_events":
            statement = statement.order_by(table.c.created_at.asc(), table.c.event_hash.asc())
        rows = db.session.execute(statement).mappings().all()
        database["tables"][table.name] = [
            {column.name: _dump_value(row[column.name], column) for column in table.columns}
            for row in rows
        ]
    return database


def _default_sources(include_git_keys: bool, include_workspaces: bool) -> dict:
    from flask import current_app

    sources: dict[str, Path] = {}
    if include_git_keys:
        sources[GITKEYS_PREFIX] = Path(current_app.config["GIT_KEY_DIR"])
    if include_workspaces:
        sources[WORKSPACES_PREFIX] = Path(current_app.config["SANDBOX_WORKSPACE_DIR"])
    return sources


def _add_tree(archive: tarfile.TarFile, base: Path, prefix: str) -> int:
    if not base.exists():
        return 0
    added = 0
    for path in sorted(p for p in base.rglob("*") if p.is_file()):
        relative = path.relative_to(base)
        data = path.read_bytes()
        info = tarfile.TarInfo(f"{prefix}/{relative.as_posix()}")
        info.size = len(data)
        info.mtime = int(path.stat().st_mtime)
        info.mode = KEY_FILE_MODE if prefix == GITKEYS_PREFIX else 0o644
        archive.addfile(info, io.BytesIO(data))
        added += 1
    return added


def _add_bytes(archive: tarfile.TarFile, name: str, data: bytes, mode: int = 0o600) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = int(utcnow().timestamp())
    info.mode = mode
    archive.addfile(info, io.BytesIO(data))


def create_backup(
    destination,
    *,
    sources: dict | None = None,
    include_git_keys: bool = True,
    include_workspaces: bool = False,
) -> dict:
    destination = Path(destination)
    database = _dump_database()
    payload = json.dumps(database, sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest = {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "created_at": utcnow().isoformat(),
        "tables": {name: len(rows) for name, rows in database["tables"].items()},
        "database": {
            "path": DATABASE_NAME,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
        "includes": {"git_keys": include_git_keys, "workspaces": include_workspaces},
    }
    if sources is None:
        sources = _default_sources(include_git_keys, include_workspaces)

    file_counts = {}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination, "w:gz") as archive:
        _add_bytes(archive, MANIFEST_NAME, json.dumps(manifest, indent=2, sort_keys=True).encode())
        _add_bytes(archive, DATABASE_NAME, payload)
        for prefix, base in sources.items():
            file_counts[prefix] = _add_tree(archive, Path(base), prefix)

    manifest["files"] = file_counts
    return manifest


def _read_member(archive: tarfile.TarFile, name: str) -> bytes:
    try:
        member = archive.getmember(name)
    except KeyError as exc:
        raise BackupError(f"backup is missing {name!r}") from exc
    extracted = archive.extractfile(member)
    if extracted is None:
        raise BackupError(f"backup entry {name!r} is not a regular file")
    return extracted.read()


def read_manifest(path) -> dict:
    path = Path(path)
    if not path.exists():
        raise BackupError(f"backup file not found: {path}")
    try:
        with tarfile.open(path, "r:gz") as archive:
            manifest = json.loads(_read_member(archive, MANIFEST_NAME))
            payload = _read_member(archive, DATABASE_NAME)
    except tarfile.TarError as exc:
        raise BackupError(f"not a valid backup archive: {exc}") from exc
    if manifest.get("format") != BACKUP_FORMAT:
        raise BackupError("unrecognised backup format")
    expected = (manifest.get("database") or {}).get("sha256")
    actual = hashlib.sha256(payload).hexdigest()
    if expected != actual:
        raise BackupError("database payload checksum mismatch (archive is corrupt or tampered)")
    manifest["verified"] = True
    return manifest


def _load_payload(path) -> dict:
    with tarfile.open(Path(path), "r:gz") as archive:
        payload = _read_member(archive, DATABASE_NAME)
    return json.loads(payload)


def _existing_rows() -> dict:
    counts = {}
    for table in _ordered_tables():
        counts[table.name] = db.session.execute(
            select(func.count()).select_from(table)
        ).scalar_one()
    return counts


def _restore_files(path, target_dirs: dict | None) -> dict:
    if not target_dirs:
        return {}
    restored = {}
    with tarfile.open(Path(path), "r:gz") as archive:
        for prefix, target in target_dirs.items():
            target = Path(target)
            if target.exists() and any(target.iterdir()):
                raise BackupError(
                    f"restore target is not empty: {target}; clear it explicitly before restoring"
                )
            count = 0
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                parts = Path(member.name).parts
                if not parts or parts[0] != prefix:
                    continue
                relative = Path(*parts[1:])
                if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                    raise BackupError(f"unsafe path in backup: {member.name}")
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(extracted.read())
                try:
                    destination.chmod(KEY_FILE_MODE if prefix == GITKEYS_PREFIX else 0o644)
                except OSError:
                    pass
                count += 1
            restored[prefix] = count
    return restored


def restore_backup(
    path,
    *,
    replace: bool = False,
    dry_run: bool = False,
    target_dirs: dict | None = None,
) -> dict:
    manifest = read_manifest(path)
    payload = _load_payload(path)
    tables = payload.get("tables") or {}
    known = {table.name for table in _ordered_tables()}
    unknown = sorted(set(tables) - known)
    if unknown:
        raise BackupError(f"backup contains unknown tables: {', '.join(unknown)}")

    existing = _existing_rows()
    non_empty = {name: count for name, count in existing.items() if count}
    if non_empty and not replace and not dry_run:
        raise BackupError(
            "target database is not empty; pass replace=True to overwrite "
            f"({len(non_empty)} tables with data)"
        )

    if dry_run:
        return {
            "dry_run": True,
            "manifest": manifest,
            "existing": existing,
            "would_restore": {name: len(rows) for name, rows in tables.items()},
        }

    try:
        for table in reversed(_ordered_tables()):
            db.session.execute(table.delete())
        for table in _ordered_tables():
            rows = tables.get(table.name) or []
            if not rows:
                continue
            db.session.execute(
                table.insert(),
                [
                    {
                        column.name: _load_value(row.get(column.name), column)
                        for column in table.columns
                    }
                    for row in rows
                ],
            )
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise BackupError(f"restore failed: {exc}") from exc

    files = _restore_files(path, target_dirs)
    return {
        "dry_run": False,
        "replaced": bool(non_empty),
        "restored": {name: len(rows) for name, rows in tables.items()},
        "files": files,
        "manifest": manifest,
    }
