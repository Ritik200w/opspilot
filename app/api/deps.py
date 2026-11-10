import hmac
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session

_bearer = HTTPBearer(auto_error=False, description="OpsPilot API token")

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def tokens_match(provided: str, expected: str) -> bool:
    """Constant-time comparison so response timing doesn't leak the token."""
    return hmac.compare_digest(provided.encode(), expected.encode())


def require_api_token(
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    expected = settings.api_token.get_secret_value()
    if not expected:
        # Fail closed: an unset token must never mean "no auth".
        raise HTTPException(status_code=503, detail="API token is not configured")
    if credentials is None or not tokens_match(credentials.credentials, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API token",
            headers={"WWW-Authenticate": "Bearer"},
        )
