import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JSONType, db_enum
from app.models.enums import FixRisk, FixStatus

if TYPE_CHECKING:
    from app.models.analysis import Analysis
    from app.models.incident import Incident


class FixProposal(Base):
    """A fix Claude proposed. Only a human moves it to approved/rejected."""

    __tablename__ = "fix_proposals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(Text)
    steps: Mapped[list[str]] = mapped_column(JSONType, default=list)
    risk: Mapped[FixRisk] = mapped_column(db_enum(FixRisk, "fix_risk"))
    status: Mapped[FixStatus] = mapped_column(
        db_enum(FixStatus, "fix_status"), default=FixStatus.PROPOSED
    )
    decided_by: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    analysis: Mapped["Analysis"] = relationship(back_populates="fix_proposals", lazy="raise")
    incident: Mapped["Incident"] = relationship(back_populates="fix_proposals", lazy="raise")
