from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_auth import get_api_user
from app.db import get_session
from app.models import User
from app.schemas import SessionRead, UserRead, UserUpdate
from app.web.session import WEB_SESSION_COOKIE, csrf_token

router = APIRouter(tags=["account"])


@router.get("/me", response_model=UserRead)
async def get_me(user: User = Depends(get_api_user)) -> User:
    return user


@router.patch("/me", response_model=UserRead)
async def update_me(
    payload: UserUpdate,
    user: User = Depends(get_api_user),
    session: AsyncSession = Depends(get_session),
) -> User:
    try:
        ZoneInfo(payload.timezone)
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid IANA timezone",
        ) from exc
    user.timezone = payload.timezone
    await session.commit()
    await session.refresh(user)
    return user


@router.get("/session", response_model=SessionRead)
async def read_session(request: Request, user: User = Depends(get_api_user)) -> SessionRead:
    raw_token = request.cookies.get(WEB_SESSION_COOKIE)
    csrf = (
        csrf_token(raw_token, request.app.state.settings)
        if raw_token is not None and getattr(request.state, "api_auth_method", None) == "cookie"
        else None
    )
    return SessionRead(user=user, csrf_token=csrf)
