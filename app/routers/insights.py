from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_auth import get_api_user
from app.db import get_session
from app.models import Entry, Food, User
from app.schemas import TopFood
from app.services.nutrition import day_bounds

router = APIRouter(prefix="/insights", tags=["insights"])


@dataclass
class _FoodTotals:
    food_id: uuid.UUID | None
    label: str
    entries: int = 0
    total_kcal: float = 0
    total_protein_g: float = 0
    total_quantity_g: float | None = None


@router.get("/top-foods", response_model=list[TopFood])
async def top_foods(
    date_from: date = Query(alias="from"),
    date_to: date = Query(alias="to"),
    limit: int = Query(default=10, ge=1, le=50),
    user: User = Depends(get_api_user),
    session: AsyncSession = Depends(get_session),
) -> list[TopFood]:
    if date_to < date_from:
        date_from, date_to = date_to, date_from
    start, _ = day_bounds(date_from, user.timezone)
    _, end = day_bounds(date_to, user.timezone)
    result = await session.execute(
        select(Entry)
        .where(
            Entry.user_id == user.id,
            Entry.logged_at >= start,
            Entry.logged_at <= end,
        )
        .order_by(Entry.logged_at)
    )
    entries = list(result.scalars())
    food_ids = {entry.food_id for entry in entries if entry.food_id is not None}
    food_names: dict[uuid.UUID, str] = {}
    if food_ids:
        foods_result = await session.execute(select(Food).where(Food.id.in_(food_ids)))
        food_names = {food.id: food.name for food in foods_result.scalars()}

    groups: dict[tuple[str, uuid.UUID | str], _FoodTotals] = {}
    for entry in entries:
        if entry.food_id is not None:
            key: tuple[str, uuid.UUID | str] = ("food", entry.food_id)
            label = food_names.get(entry.food_id, entry.description or "Alimento")
        else:
            normalized = (entry.description or "").strip().lower()
            key = ("description", normalized)
            label = entry.description or "Alimento"
        group = groups.setdefault(key, _FoodTotals(food_id=entry.food_id, label=label))
        group.entries += 1
        group.total_kcal += float(entry.kcal)
        group.total_protein_g += float(entry.protein_g)
        if entry.quantity_g is not None:
            group.total_quantity_g = (group.total_quantity_g or 0) + float(entry.quantity_g)

    ordered = sorted(groups.values(), key=lambda group: group.total_kcal, reverse=True)[:limit]
    return [
        TopFood(
            food_id=group.food_id,
            label=group.label,
            entries=group.entries,
            total_kcal=round(group.total_kcal, 2),
            total_protein_g=round(group.total_protein_g, 2),
            total_quantity_g=(
                round(group.total_quantity_g, 2) if group.total_quantity_g is not None else None
            ),
            avg_kcal=round(group.total_kcal / group.entries, 2),
        )
        for group in ordered
    ]
