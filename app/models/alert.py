import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JSONType, db_enum
from app.models.enums import AlertSource, AlertStatus, Severity

if TYPE_CHECKING:
    from app.models.incident import Incident


class Alert(Base):
    """One raw alert as received from a webhook, normalized."""

    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[AlertSource] = mapped_column(db_enum(AlertSource, "alert_source"))
    fingerprint: Mapped[str] = mapped_column(Text, index=True)
    status: Mapped[AlertStatus] = mapped_column(db_enum(AlertStatus, "alert_status"))
    severity: Mapped[Severity] = mapped_column(db_enum(Severity, "severity"))
    service: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    labels: Mapped[dict[str, str]] = mapped_column(JSONType, default=dict)
    annotations: Mapped[dict[str, str]] = mapped_column(JSONType, default=dict)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    incident: Mapped["Incident"] = relationship(back_populates="alerts", lazy="raise")
