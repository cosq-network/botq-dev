import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def _migration_module():
    path = Path(__file__).parents[1] / "migrations" / "versions" / "f2a7c9e4d1b6_project_gate_control.py"
    spec = importlib.util.spec_from_file_location("project_gate_control_migration", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_project_gate_migration_upgrades_and_downgrades():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        migration = _migration_module()
        migration.op = operations

        migration.upgrade()
        tables = set(inspect(connection).get_table_names())
        assert {
            "project_gates",
            "project_gate_evidence",
            "project_gate_decisions",
            "project_gate_history",
        } <= tables

        migration.downgrade()
        tables = set(inspect(connection).get_table_names())
        assert not {
            "project_gates",
            "project_gate_evidence",
            "project_gate_decisions",
            "project_gate_history",
        } & tables
