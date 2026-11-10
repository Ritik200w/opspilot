import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Text, false, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JSONType, db_enum
from app.models.enums import ContextKind

if TYPE_CHECKING:
    from app.models.incident import Incident


class ContextSnapshot(Base):
    """Metrics or logs collected for an incident, kept for audit and replay."""

    __tablename__ = "context_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[ContextKind] = mapped_column(db_enum(ContextKind, "context_kind"))
    query: Mapped[str] = mapped_column(Text)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    truncated: Mapped[bool] = mapped_column(default=False, server_default=false())
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    incident: Mapped["Incident"] = relationship(back_populates="context_snapshots", lazy="raise")
