import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IncidentStatus
from tests.factories import make_incident

pytestmark = pytest.mark.anyio


async def test_two_open_incidents_cannot_share_dedup_key(session: AsyncSession) -> None:
    session.add_all([make_incident(dedup_key="k"), make_incident(dedup_key="k")])

    with pytest.raises(IntegrityError):
        await session.commit()


async def test_resolved_incident_does_not_block_new_open_one(session: AsyncSession) -> None:
    session.add_all(
        [
            make_incident(dedup_key="k", status=IncidentStatus.RESOLVED),
            make_incident(dedup_key="k", status=IncidentStatus.RESOLVED),
            make_incident(dedup_key="k", status=IncidentStatus.OPEN),
        ]
    )

    await session.commit()  # no IntegrityError
