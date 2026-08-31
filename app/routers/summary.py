from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Entry, Goal, Meal, User
from app.schemas import DailySummary, Progress, RangeSummary, Totals
from app.security import get_current_user
from app.services.nutrition import MacroValues, day_bounds, effective_goal, totals

router = APIRouter(prefix="/summary", tags=["summary"])


def totals_schema(values: MacroValues) -> Totals:
    return Totals(
        kcal=values.kcal or 0,
        protein_g=values.protein_g or 0,
        carbs_g=values.carbs_g or 0,
        fat_g=values.fat_g or 0,
        fiber_g=values.fiber_g or 0,
    )


def goal_schema(goal: Goal | None) -> Totals | None:
    if goal is None:
        return None
    return Totals(
        kcal=float(goal.kcal),
        protein_g=float(goal.protein_g),
        carbs_g=float(goal.carbs_g),
        fat_g=float(goal.fat_g),
        fiber_g=float(goal.fiber_g or 0),
    )


def progress(consumed: Totals, goal: Totals | None) -> Progress:
    if goal is None:
        return Progress(
            consumed=consumed,
            goal=None,
            remaining=None,
            percent=Totals(kcal=0, protein_g=0, carbs_g=0, fat_g=0, fiber_g=0),
        )
    remaining = Totals(
        kcal=round(goal.kcal - consumed.kcal, 2),
        protein_g=round(goal.protein_g - consumed.protein_g, 2),
        carbs_g=round(goal.carbs_g - consumed.carbs_g, 2),
        fat_g=round(goal.fat_g - consumed.fat_g, 2),
        fiber_g=round(goal.fiber_g - consumed.fiber_g, 2) if goal.fiber_g else 0,
    )
    percent = Totals(
        kcal=round(consumed.kcal / goal.kcal * 100, 1) if goal.kcal else 0,
        protein_g=round(consumed.protein_g / goal.protein_g * 100, 1) if goal.protein_g else 0,
        carbs_g=round(consumed.carbs_g / goal.carbs_g * 100, 1) if goal.carbs_g else 0,
        fat_g=round(consumed.fat_g / goal.fat_g * 100, 1) if goal.fat_g else 0,
        fiber_g=round(consumed.fiber_g / goal.fiber_g * 100, 1) if goal.fiber_g else 0,
    )
    return Progress(consumed=consumed, goal=goal, remaining=remaining, percent=percent)


def make_daily_summary(day: date, entries: list[Entry], goals: list[Goal]) -> DailySummary:
    goal = effective_goal(goals, day)
    consumed = totals(entries)
    consumed_schema = totals_schema(consumed)
    by_meal: dict[str, Totals] = {}
    for meal in Meal:
        by_meal[meal.value] = totals_schema(
            totals(entry for entry in entries if entry.meal == meal)
        )
    result = progress(consumed_schema, goal_schema(goal))
    return DailySummary(
        date=day,
        entries_count=len(entries),
        by_meal=by_meal,
        consumed=result.consumed,
        goal=result.goal,
        remaining=result.remaining,
        percent=result.percent,
    )


async def build_daily_summary(day: date, user: User, session: AsyncSession) -> DailySummary:
    start, end = day_bounds(day, user.timezone)
    entries_result = await session.execute(
        select(Entry).where(
            Entry.user_id == user.id, Entry.logged_at >= start, Entry.logged_at <= end
        )
    )
    entries = list(entries_result.scalars())
    goals_result = await session.execute(select(Goal).where(Goal.user_id == user.id))
    return make_daily_summary(day, entries, list(goals_result.scalars()))


async def build_range_summary(
    date_from: date, date_to: date, user: User, session: AsyncSession
) -> RangeSummary:
    if date_to < date_from:
        date_from, date_to = date_to, date_from
    start, _ = day_bounds(date_from, user.timezone)
    _, end = day_bounds(date_to, user.timezone)
    entries_result = await session.execute(
        select(Entry).where(
            Entry.user_id == user.id,
            Entry.logged_at >= start,
            Entry.logged_at <= end,
        )
    )
    goals_result = await session.execute(
        select(Goal).where(Goal.user_id == user.id, Goal.effective_from <= date_to)
    )
    entries = list(entries_result.scalars())
    goals = list(goals_result.scalars())
    local_zone = ZoneInfo(user.timezone)
    entries_by_day: dict[date, list[Entry]] = {}
    for entry in entries:
        entry_day = entry.logged_at.astimezone(local_zone).date()
        entries_by_day.setdefault(entry_day, []).append(entry)
    days = [
        make_daily_summary(
            date_from + timedelta(days=offset),
            entries_by_day.get(date_from + timedelta(days=offset), []),
            goals,
        )
        for offset in range((date_to - date_from).days + 1)
    ]
    count = len(days)
    averages = Totals(
        kcal=round(sum(day.consumed.kcal for day in days) / count, 2),
        protein_g=round(sum(day.consumed.protein_g for day in days) / count, 2),
        carbs_g=round(sum(day.consumed.carbs_g for day in days) / count, 2),
        fat_g=round(sum(day.consumed.fat_g for day in days) / count, 2),
        fiber_g=round(sum(day.consumed.fiber_g for day in days) / count, 2),
    )
    return RangeSummary(days=days, averages=averages)


@router.get("/daily", response_model=DailySummary)
async def daily_summary(
    summary_date: date | None = Query(default=None, alias="date"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DailySummary:
    target = summary_date or datetime.now(ZoneInfo(user.timezone)).date()
    return await build_daily_summary(target, user, session)


@router.get("/range", response_model=RangeSummary)
async def range_summary(
    date_from: date = Query(alias="from"),
    date_to: date = Query(alias="to"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RangeSummary:
    return await build_range_summary(date_from, date_to, user, session)
