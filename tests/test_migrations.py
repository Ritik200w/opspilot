"""The migration can't run against SQLite (JSONB, enum types), so we render its PostgreSQL SQL
offline and check it against the ORM models. This catches model/migration drift without a DB."""

import io
import re
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.models import Base

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def upgrade_sql() -> str:
    buffer = io.StringIO()
    config = Config(output_buffer=buffer)
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", "postgresql+asyncpg://user:pw@localhost/db")
    command.upgrade(config, "head", sql=True)
    return buffer.getvalue()


def _create_table_block(sql: str, table: str) -> str:
    match = re.search(rf"CREATE TABLE {table} \((.*?)\n\);", sql, re.DOTALL)
    assert match, f"no CREATE TABLE for {table}"
    return match.group(1)


def test_partial_unique_index_on_open_incidents(upgrade_sql: str) -> None:
    assert (
        "CREATE UNIQUE INDEX uq_incidents_open_dedup_key ON incidents (dedup_key) "
        "WHERE status <> 'resolved'"
    ) in upgrade_sql


def test_every_model_column_is_in_the_migration(upgrade_sql: str) -> None:
    for table in Base.metadata.sorted_tables:
        block = _create_table_block(upgrade_sql, table.name)
        for column in table.columns:
            assert re.search(rf"^\s+{column.name} ", block, re.MULTILINE), (
                f"{table.name}.{column.name} missing from migration"
            )


def test_migration_has_no_columns_missing_from_models(upgrade_sql: str) -> None:
    for table in Base.metadata.sorted_tables:
        block = _create_table_block(upgrade_sql, table.name)
        # Column lines look like "    name TYPE ..."; enum types are lowercase (e.g. "severity").
        migration_cols = set(re.findall(r"^\s+(\w+) \S", block, re.MULTILINE)) - {"CONSTRAINT"}
        assert migration_cols == {c.name for c in table.columns}, table.name


def test_model_indexes_exist_in_migration(upgrade_sql: str) -> None:
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            assert f"INDEX {index.name} ON {table.name}" in upgrade_sql, index.name


def test_enum_types_created(upgrade_sql: str) -> None:
    assert "CREATE TYPE severity AS ENUM ('critical', 'warning', 'info')" in upgrade_sql
    assert "CREATE TYPE incident_status AS ENUM" in upgrade_sql
