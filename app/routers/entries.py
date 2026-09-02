import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_auth import get_api_user
from app.db import get_session
from app.models import Entry, Food, User
from app.schemas import EntryCreate, EntryRead, EntryUpdate
from app.services.nutrition import MacroValues, resolve_entry_macros

router = APIRouter(prefix="/entries", tags=["entries"])


async def find_food(food_id: uuid.UUID | None, user: User, session: AsyncSession) -> Food | None:
    if food_id is None:
        return None
    result = await session.execute(
        select(Food).where(Food.id == food_id, (Food.user_id == user.id) | Food.user_id.is_(None))
    )
    food = result.scalar_one_or_none()
    if food is None:
        raise HTTPException(status_code=404, detail="Food not found")
    return food


def entry_overrides(payload: EntryCreate | EntryUpdate) -> MacroValues:
    return MacroValues(
        kcal=payload.kcal,
        protein_g=payload.protein_g,
        carbs_g=payload.carbs_g,
        fat_g=payload.fat_g,
        fiber_g=payload.fiber_g,
    )


@router.post("", response_model=EntryRead, status_code=status.HTTP_201_CREATED)
async def create_entry(
    payload: EntryCreate,
    user: User = Depends(get_api_user),
    session: AsyncSession = Depends(get_session),
) -> Entry:
    food = await find_food(payload.food_id, user, session)
    try:
        macros = resolve_entry_macros(food, payload.quantity_g, entry_overrides(payload))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    logged_at = payload.logged_at or datetime.now(UTC)
    if logged_at.tzinfo is None:
        logged_at = logged_at.replace(tzinfo=UTC)
    entry = Entry(
        user_id=user.id,
        logged_at=logged_at,
        meal=payload.meal,
        food_id=payload.food_id,
        description=payload.description
        or (food.name if food is not None and food.expires_at else None),
        quantity_g=payload.quantity_g,
        kcal=macros.kcal,
        protein_g=macros.protein_g,
        carbs_g=macros.carbs_g,
        fat_g=macros.fat_g,
        fiber_g=macros.fiber_g,
        notes=payload.notes,
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


@router.get("", response_model=list[EntryRead])
async def list_entries(
    entry_date: date | None = Query(default=None, alias="date"),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    user: User = Depends(get_api_user),
    session: AsyncSession = Depends(get_session),
) -> list[Entry]:
    from app.services.nutrition import day_bounds

    query = select(Entry).where(Entry.user_id == user.id)
    if entry_date:
        start, end = day_bounds(entry_date, user.timezone)
        query = query.where(Entry.logged_at >= start, Entry.logged_at <= end)
    elif date_from or date_to:
        if date_from:
            start, _ = day_bounds(date_from, user.timezone)
            query = query.where(Entry.logged_at >= start)
        if date_to:
            _, end = day_bounds(date_to, user.timezone)
            query = query.where(Entry.logged_at <= end)
    result = await session.execute(query.order_by(Entry.logged_at))
    return list(result.scalars())


@router.get("/{entry_id}", response_model=EntryRead)
async def get_entry(
    entry_id: uuid.UUID,
    user: User = Depends(get_api_user),
    session: AsyncSession = Depends(get_session),
) -> Entry:
    result = await session.execute(
        select(Entry).where(Entry.id == entry_id, Entry.user_id == user.id)
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


@router.patch("/{entry_id}", response_model=EntryRead)
async def update_entry(
    entry_id: uuid.UUID,
    payload: EntryUpdate,
    user: User = Depends(get_api_user),
    session: AsyncSession = Depends(get_session),
) -> Entry:
    result = await session.execute(
        select(Entry).where(Entry.id == entry_id, Entry.user_id == user.id)
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    data = payload.model_dump(exclude_unset=True)
    food_id = data.get("food_id", entry.food_id)
    quantity_g = data.get(
        "quantity_g", float(entry.quantity_g) if entry.quantity_g is not None else None
    )
    food = await find_food(food_id, user, session)
    use_calculated_macros = food is not None and quantity_g is not None
    macros = resolve_entry_macros(
        food,
        quantity_g,
        MacroValues(
            kcal=data.get("kcal") if use_calculated_macros else data.get("kcal", float(entry.kcal)),
            protein_g=data.get("protein_g")
            if use_calculated_macros
            else data.get("protein_g", float(entry.protein_g)),
            carbs_g=data.get("carbs_g")
            if use_calculated_macros
            else data.get("carbs_g", float(entry.carbs_g)),
            fat_g=data.get("fat_g")
            if use_calculated_macros
            else data.get("fat_g", float(entry.fat_g)),
            fiber_g=data.get("fiber_g")
            if use_calculated_macros
            else data.get("fiber_g", float(entry.fiber_g) if entry.fiber_g is not None else None),
        ),
    )
    if "logged_at" in data:
        logged_at = data["logged_at"]
        entry.logged_at = logged_at.replace(tzinfo=UTC) if logged_at.tzinfo is None else logged_at
    if "meal" in data:
        entry.meal = data["meal"]
    if "food_id" in data:
        entry.food_id = data["food_id"]
    if "description" in data:
        entry.description = data["description"]
    if "quantity_g" in data:
        entry.quantity_g = data["quantity_g"]
    if "notes" in data:
        entry.notes = data["notes"]
    assert macros.kcal is not None
    assert macros.protein_g is not None
    assert macros.carbs_g is not None
    assert macros.fat_g is not None
    entry.kcal = Decimal(str(macros.kcal))
    entry.protein_g = Decimal(str(macros.protein_g))
    entry.carbs_g = Decimal(str(macros.carbs_g))
    entry.fat_g = Decimal(str(macros.fat_g))
    entry.fiber_g = Decimal(str(macros.fiber_g)) if macros.fiber_g is not None else None
    await session.commit()
    await session.refresh(entry)
    return entry


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(
    entry_id: uuid.UUID,
    user: User = Depends(get_api_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    result = await session.execute(
        select(Entry).where(Entry.id == entry_id, Entry.user_id == user.id)
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    await session.delete(entry)
    await session.commit()
