"""``flask backup`` CLI: create, inspect/verify and restore backups (REQ-INF-07)."""

from pathlib import Path

import click
from flask import current_app
from flask.cli import with_appcontext

from .service import (
    GITKEYS_PREFIX,
    WORKSPACES_PREFIX,
    BackupError,
    create_backup,
    read_manifest,
    restore_backup,
)


@click.group("backup")
def backup_cli():
    """Create and restore platform backups."""


@backup_cli.command("create")
@click.option("--output", "-o", required=True, type=click.Path(), help="Destination .tar.gz path.")
@click.option("--include-workspaces/--no-include-workspaces", default=False)
@click.option("--include-git-keys/--no-include-git-keys", default=True)
@with_appcontext
def create_command(output, include_workspaces, include_git_keys):
    """Write a portable backup archive."""
    try:
        manifest = create_backup(
            output,
            include_workspaces=include_workspaces,
            include_git_keys=include_git_keys,
        )
    except BackupError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Backup written: {Path(output).resolve()}")
    click.echo(f"Created at:     {manifest['created_at']}")
    click.echo(f"Tables:         {sum(manifest['tables'].values())} rows")
    for name, count in sorted(manifest["tables"].items()):
        click.echo(f"  - {name}: {count}")


@backup_cli.command("verify")
@click.argument("archive", type=click.Path(exists=True))
def verify_command(archive):
    """Verify an archive's integrity and print its manifest."""
    try:
        manifest = read_manifest(archive)
    except BackupError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"OK: {archive}")
    click.echo(f"Format:   {manifest['format']} v{manifest['version']}")
    click.echo(f"Created:  {manifest['created_at']}")
    click.echo(f"Checksum: {manifest['database']['sha256']}")


@backup_cli.command("restore")
@click.argument("archive", type=click.Path(exists=True))
@click.option("--replace", is_flag=True, help="Overwrite existing rows (destructive).")
@click.option("--dry-run", is_flag=True, help="Validate and report without writing.")
@click.option("--restore-files/--no-restore-files", default=True)
@with_appcontext
def restore_command(archive, replace, dry_run, restore_files):
    """Restore a backup archive into the configured database."""
    target_dirs = None
    if restore_files and not dry_run:
        target_dirs = {
            GITKEYS_PREFIX: current_app.config["GIT_KEY_DIR"],
            WORKSPACES_PREFIX: current_app.config["SANDBOX_WORKSPACE_DIR"],
        }
    try:
        result = restore_backup(archive, replace=replace, dry_run=dry_run, target_dirs=target_dirs)
    except BackupError as exc:
        raise click.ClickException(str(exc)) from exc
    if result["dry_run"]:
        click.echo("Dry run - nothing written.")
        click.echo(f"Existing rows: {sum(result['existing'].values())}")
        click.echo(f"Would restore: {sum(result['would_restore'].values())} rows")
        return
    click.echo(f"Restored {sum(result['restored'].values())} rows")
    if result.get("replaced"):
        click.echo("Existing data was replaced.")
    if result.get("files"):
        for prefix, count in result["files"].items():
            click.echo(f"Restored {count} file(s) into {prefix}/")
