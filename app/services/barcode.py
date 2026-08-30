import asyncio
import logging
import re

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Food, User
from app.providers.base import BarcodeProvider, ProviderError, ProviderFood
from app.providers.registry import SOURCE_PRIORITY, get_enabled_providers
from app.services.food_cache import upsert_provider_foods

logger = logging.getLogger(__name__)


def normalize_barcode(barcode: str) -> str:
    return re.sub(r"\D", "", barcode)


async def lookup_barcode(
    session: AsyncSession,
    *,
    user: User,
    barcode: str,
) -> Food | None:
    normalized = normalize_barcode(barcode)
    if not normalized:
        return None

    local = await _find_local(session, user=user, barcode=normalized)
    if local is not None:
        return local

    providers = {
        source: provider
        for source, provider in get_enabled_providers().items()
        if isinstance(provider, BarcodeProvider)
    }

    async def fetch(provider_source: str, provider: BarcodeProvider) -> ProviderFood | None:
        try:
            return await asyncio.wait_for(provider.fetch_barcode(normalized), timeout=3.0)
        except (ProviderError, TimeoutError) as exc:
            logger.warning("Barcode provider %s unavailable: %s", provider_source, exc)
        except Exception:
            logger.warning("Barcode provider %s failed", provider_source, exc_info=True)
        return None

    results = await asyncio.gather(
        *(fetch(source, provider) for source, provider in providers.items()),
        return_exceptions=True,
    )
    provider_foods: list[ProviderFood] = []
    for result in results:
        if isinstance(result, BaseException):
            logger.warning("Barcode provider lookup failed: %s", result)
        elif result is not None:
            provider_foods.append(result)
    if provider_foods:
        await upsert_provider_foods(session, provider_foods)
        await session.commit()
    return await _find_local(session, user=user, barcode=normalized)


async def _find_local(session: AsyncSession, *, user: User, barcode: str) -> Food | None:
    source_priority = case(
        (Food.user_id.is_not(None), 0),
        *(
            (Food.source == source, priority)
            for source, priority in SOURCE_PRIORITY.items()
            if source is not None
        ),
        else_=SOURCE_PRIORITY[None],
    )
    result = await session.execute(
        select(Food)
        .where(
            Food.barcode == barcode,
            (Food.user_id == user.id) | Food.user_id.is_(None),
            Food.archived_at.is_(None),
            (Food.expires_at.is_(None) | (Food.expires_at > func.now())),
        )
        .order_by(source_priority, Food.name)
        .limit(1)
    )
    return result.scalar_one_or_none()
