"""
get_current_user is the ONLY place identity is established. Every router that
needs to know "who is making this request" depends on this function — never
on a user_id field read out of the request body.
"""
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.services import security
from app.services.auth_service import get_user_by_id
from app.utils.exceptions import InvalidToken

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise InvalidToken("Missing authentication token.")

    try:
        payload = security.decode_access_token(credentials.credentials)
    except JWTError as exc:
        raise InvalidToken() from exc

    user_id = payload.get("sub")
    if not user_id:
        raise InvalidToken()

    user = await get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise InvalidToken("Account not found or disabled.")

    return user


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def client_user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")
