from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_auth import get_api_user
from app.db import get_session
from app.models import Goal, User
from app.schemas import GoalCreate, GoalRead

router = APIRouter(prefix="/goals", tags=["goals"])


@router.put("", response_model=GoalRead)
async def upsert_goal(
    payload: GoalCreate,
    user: User = Depends(get_api_user),
    session: AsyncSession = Depends(get_session),
) -> Goal:
    effective_from = payload.effective_from or datetime.now(ZoneInfo(user.timezone)).date()
    result = await session.execute(
        select(Goal).where(Goal.user_id == user.id, Goal.effective_from == effective_from)
    )
    goal = result.scalar_one_or_none()
    values = payload.model_dump(exclude={"effective_from"})
    if goal is None:
        goal = Goal(user_id=user.id, effective_from=effective_from, **values)
        session.add(goal)
    else:
        goal.kcal = values["kcal"]
        goal.protein_g = values["protein_g"]
        goal.carbs_g = values["carbs_g"]
        goal.fat_g = values["fat_g"]
        goal.fiber_g = values["fiber_g"]
    await session.commit()
    await session.refresh(goal)
    return goal


@router.get("/current", response_model=GoalRead | None)
async def current_goal(
    goal_date: date | None = Query(default=None, alias="date"),
    user: User = Depends(get_api_user),
    session: AsyncSession = Depends(get_session),
) -> Goal | None:
    target = goal_date or datetime.now(ZoneInfo(user.timezone)).date()
    result = await session.execute(
        select(Goal)
        .where(Goal.user_id == user.id, Goal.effective_from <= target)
        .order_by(Goal.effective_from.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


@router.get("", response_model=list[GoalRead])
async def list_goals(
    user: User = Depends(get_api_user),
    session: AsyncSession = Depends(get_session),
) -> list[Goal]:
    result = await session.execute(
        select(Goal).where(Goal.user_id == user.id).order_by(Goal.effective_from.desc())
    )
    return list(result.scalars())
