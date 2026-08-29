import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Food, User
from app.schemas import FoodCreate, FoodRead, FoodUpdate
from app.security import get_current_user
from app.text import search_terms

router = APIRouter(prefix="/foods", tags=["foods"])


@router.post("", response_model=FoodRead, status_code=status.HTTP_201_CREATED)
async def create_food(
    payload: FoodCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Food:
    food = Food(user_id=user.id, **payload.model_dump())
    session.add(food)
    await session.commit()
    await session.refresh(food)
    return food


@router.get("", response_model=list[FoodRead])
async def list_foods(
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Food]:
    query = select(Food).where(or_(Food.user_id == user.id, Food.user_id.is_(None)))
    terms = search_terms(search or "")
    for term in terms:
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        fallback = f"%{search or ''}%"
        query = query.where(
            or_(
                Food.search_text.like(f"%{escaped}%", escape="\\"),
                Food.search_text.is_(None)
                & (Food.name.ilike(fallback) | Food.brand.ilike(fallback)),
            )
        )
    result = await session.execute(
        query.order_by(Food.user_id.is_(None), func.length(Food.name), Food.name).limit(limit)
    )
    return list(result.scalars())


@router.get("/{food_id}", response_model=FoodRead)
async def get_food(
    food_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Food:
    result = await session.execute(
        select(Food).where(Food.id == food_id, or_(Food.user_id == user.id, Food.user_id.is_(None)))
    )
    food = result.scalar_one_or_none()
    if food is None:
        raise HTTPException(status_code=404, detail="Food not found")
    return food


@router.patch("/{food_id}", response_model=FoodRead)
async def update_food(
    food_id: uuid.UUID,
    payload: FoodUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Food:
    result = await session.execute(select(Food).where(Food.id == food_id, Food.user_id == user.id))
    food = result.scalar_one_or_none()
    if food is None:
        raise HTTPException(status_code=404, detail="Food not found")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        food.name = data["name"]
    if "brand" in data:
        food.brand = data["brand"]
    if "category" in data:
        food.category = data["category"]
    if "kcal" in data:
        food.kcal = data["kcal"]
    if "protein_g" in data:
        food.protein_g = data["protein_g"]
    if "carbs_g" in data:
        food.carbs_g = data["carbs_g"]
    if "fat_g" in data:
        food.fat_g = data["fat_g"]
    if "fiber_g" in data:
        food.fiber_g = data["fiber_g"]
    if "serving_label" in data:
        food.serving_label = data["serving_label"]
    if "serving_grams" in data:
        food.serving_grams = data["serving_grams"]
    await session.commit()
    await session.refresh(food)
    return food


@router.delete("/{food_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_food(
    food_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    result = await session.execute(select(Food).where(Food.id == food_id, Food.user_id == user.id))
    food = result.scalar_one_or_none()
    if food is None:
        raise HTTPException(status_code=404, detail="Food not found")
    await session.delete(food)
    await session.commit()
