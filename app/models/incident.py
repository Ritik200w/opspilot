import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Index, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, db_enum
from app.models.enums import IncidentStatus, Severity

if TYPE_CHECKING:
    from app.models.alert import Alert
    from app.models.analysis import Analysis
    from app.models.context_snapshot import ContextSnapshot
    from app.models.fix_proposal import FixProposal

OPEN_INCIDENT_PREDICATE = text("status <> 'resolved'")


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        # At most one non-resolved incident per dedup key.
        Index(
            "uq_incidents_open_dedup_key",
            "dedup_key",
            unique=True,
            postgresql_where=OPEN_INCIDENT_PREDICATE,
            sqlite_where=OPEN_INCIDENT_PREDICATE,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    dedup_key: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    service: Mapped[str] = mapped_column(Text, index=True)
    severity: Mapped[Severity] = mapped_column(db_enum(Severity, "severity"))
    status: Mapped[IncidentStatus] = mapped_column(
        db_enum(IncidentStatus, "incident_status"), default=IncidentStatus.OPEN, index=True
    )
    slack_channel: Mapped[str | None] = mapped_column(Text)
    slack_ts: Mapped[str | None] = mapped_column(Text)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="incident", lazy="raise", order_by="Alert.received_at"
    )
    context_snapshots: Mapped[list["ContextSnapshot"]] = relationship(
        back_populates="incident", lazy="raise"
    )
    analyses: Mapped[list["Analysis"]] = relationship(back_populates="incident", lazy="raise")
    fix_proposals: Mapped[list["FixProposal"]] = relationship(
        back_populates="incident", lazy="raise"
    )
