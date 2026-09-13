from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Food
from app.providers.base import ProviderFood
from app.text import normalize_search_text


async def upsert_provider_foods(
    session: AsyncSession,
    foods: Sequence[ProviderFood],
    *,
    ttl: timedelta | None = None,
) -> list[Food]:
    """Materialize provider results as global foods without touching user foods."""
    unique_foods = {(food.source, food.source_ref): food for food in foods}
    if not unique_foods:
        return []

    now = datetime.now(UTC)
    expires_at = now + ttl if ttl is not None else None
    rows = [
        {
            "user_id": None,
            "source": food.source,
            "source_ref": food.source_ref,
            "name": food.name,
            "brand": food.brand,
            "category": food.category,
            "search_text": normalize_search_text(food.name, food.brand, food.category),
            "kcal": food.kcal,
            "protein_g": food.protein_g,
            "carbs_g": food.carbs_g,
            "fat_g": food.fat_g,
            "fiber_g": food.fiber_g,
            "source_version": food.source_version,
            "attribution": food.attribution,
            "barcode": food.barcode,
            "locale": food.locale,
            "nutrients": food.nutrients,
            "fetched_at": now,
            "expires_at": expires_at,
            "archived_at": None,
            "created_at": now,
            "updated_at": now,
        }
        for food in unique_foods.values()
    ]
    statement = insert(Food).values(rows)
    update_values = {
        key: statement.excluded[key]
        for key in rows[0]
        if key not in {"id", "user_id", "source", "source_ref", "created_at"}
    }
    statement = statement.on_conflict_do_update(
        index_elements=["source", "source_ref"],
        index_where=text("source is not null"),
        set_=update_values,
        where=Food.user_id.is_(None),
    )
    await session.execute(statement)
    await session.flush()

    keys = list(unique_foods)
    result = await session.execute(
        select(Food).where(
            Food.user_id.is_(None),
            tuple_(Food.source, Food.source_ref).in_(keys),
        )
    )
    by_key = {(food.source, food.source_ref): food for food in result.scalars()}
    return [by_key[key] for key in keys if key in by_key]
