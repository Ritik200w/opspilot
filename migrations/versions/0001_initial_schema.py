"""initial schema: incidents, alerts, context_snapshots, analyses, fix_proposals

Revision ID: 0001
Revises:
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUMS: dict[str, tuple[str, ...]] = {
    "severity": ("critical", "warning", "info"),
    "incident_status": ("open", "analyzing", "analyzed", "failed", "resolved"),
    "alert_source": ("alertmanager", "generic"),
    "alert_status": ("firing", "resolved"),
    "context_kind": ("metrics", "logs"),
    "fix_risk": ("low", "medium", "high"),
    "fix_status": ("proposed", "approved", "rejected"),
}


def _enum(name: str) -> postgresql.ENUM:
    # Types are created explicitly below; don't let create_table emit CREATE TYPE again.
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def _ts(name: str, *, nullable: bool = False, default_now: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=sa.func.now() if default_now else None,
    )


def _id() -> sa.Column:
    return sa.Column("id", sa.Uuid(), nullable=False)


def _incident_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["incident_id"],
        ["incidents.id"],
        name=f"fk_{table}_incident_id_incidents",
        ondelete="CASCADE",
    )


def _create_enums() -> None:
    for name, values in ENUMS.items():
        quoted = ", ".join(f"'{value}'" for value in values)
        op.execute(f"CREATE TYPE {name} AS ENUM ({quoted})")


def _create_incidents() -> None:
    op.create_table(
        "incidents",
        _id(),
        sa.Column("dedup_key", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("service", sa.Text(), nullable=False),
        sa.Column("severity", _enum("severity"), nullable=False),
        sa.Column("status", _enum("incident_status"), nullable=False),
        sa.Column("slack_channel", sa.Text(), nullable=True),
        sa.Column("slack_ts", sa.Text(), nullable=True),
        _ts("opened_at", default_now=True),
        _ts("resolved_at", nullable=True),
        _ts("created_at", default_now=True),
        _ts("updated_at", default_now=True),
        sa.PrimaryKeyConstraint("id", name="pk_incidents"),
    )
    op.create_index("ix_incidents_service", "incidents", ["service"])
    op.create_index("ix_incidents_status", "incidents", ["status"])
    op.create_index("ix_incidents_opened_at", "incidents", ["opened_at"])
    op.create_index(
        "uq_incidents_open_dedup_key",
        "incidents",
        ["dedup_key"],
        unique=True,
        postgresql_where=sa.text("status <> 'resolved'"),
    )


def _create_alerts() -> None:
    op.create_table(
        "alerts",
        _id(),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("source", _enum("alert_source"), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("status", _enum("alert_status"), nullable=False),
        sa.Column("severity", _enum("severity"), nullable=False),
        sa.Column("service", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("labels", postgresql.JSONB(), nullable=False),
        sa.Column("annotations", postgresql.JSONB(), nullable=False),
        _ts("starts_at"),
        _ts("ends_at", nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        _ts("received_at", default_now=True),
        sa.PrimaryKeyConstraint("id", name="pk_alerts"),
        _incident_fk("alerts"),
    )
    op.create_index("ix_alerts_incident_id", "alerts", ["incident_id"])
    op.create_index("ix_alerts_fingerprint", "alerts", ["fingerprint"])


def _create_context_snapshots() -> None:
    op.create_table(
        "context_snapshots",
        _id(),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("kind", _enum("context_kind"), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        _ts("window_start"),
        _ts("window_end"),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        _ts("collected_at", default_now=True),
        sa.PrimaryKeyConstraint("id", name="pk_context_snapshots"),
        _incident_fk("context_snapshots"),
    )
    op.create_index("ix_context_snapshots_incident_id", "context_snapshots", ["incident_id"])


def _create_analyses() -> None:
    op.create_table(
        "analyses",
        _id(),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        _ts("created_at", default_now=True),
        sa.PrimaryKeyConstraint("id", name="pk_analyses"),
        _incident_fk("analyses"),
    )
    op.create_index("ix_analyses_incident_id", "analyses", ["incident_id"])


def _create_fix_proposals() -> None:
    op.create_table(
        "fix_proposals",
        _id(),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("steps", postgresql.JSONB(), nullable=False),
        sa.Column("risk", _enum("fix_risk"), nullable=False),
        sa.Column("status", _enum("fix_status"), nullable=False),
        sa.Column("decided_by", sa.Text(), nullable=True),
        _ts("decided_at", nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        _ts("created_at", default_now=True),
        sa.PrimaryKeyConstraint("id", name="pk_fix_proposals"),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name="fk_fix_proposals_analysis_id_analyses",
            ondelete="CASCADE",
        ),
        _incident_fk("fix_proposals"),
    )
    op.create_index("ix_fix_proposals_analysis_id", "fix_proposals", ["analysis_id"])
    op.create_index("ix_fix_proposals_incident_id", "fix_proposals", ["incident_id"])


def upgrade() -> None:
    _create_enums()
    _create_incidents()
    _create_alerts()
    _create_context_snapshots()
    _create_analyses()
    _create_fix_proposals()


def downgrade() -> None:
    for table in ("fix_proposals", "analyses", "context_snapshots", "alerts", "incidents"):
        op.drop_table(table)  # indexes are dropped with their tables
    for name in reversed(ENUMS):
        op.execute(f"DROP TYPE {name}")
