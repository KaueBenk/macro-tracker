import asyncio
import logging
from collections.abc import Sequence

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Food, User
from app.providers.base import FoodProvider, ProviderError, ProviderFood
from app.providers.registry import SOURCE_PRIORITY, get_enabled_providers
from app.services.food_cache import upsert_provider_foods
from app.text import normalize_search_text, search_terms

logger = logging.getLogger(__name__)


async def search_foods(
    session: AsyncSession,
    *,
    user: User,
    query: str,
    limit: int,
    sources: Sequence[str] | None = None,
    remote: bool = False,
) -> list[Food]:
    if remote and normalize_search_text(query):
        providers = get_enabled_providers()
        if sources is not None:
            requested_sources = set(sources)
            providers = {
                source: provider
                for source, provider in providers.items()
                if source in requested_sources
            }

        async def fetch(provider_source: str, provider: FoodProvider) -> list[ProviderFood]:
            try:
                result = await asyncio.wait_for(
                    provider.search(query, limit),
                    timeout=get_settings().provider_timeout_seconds,
                )
                return result
            except (ProviderError, TimeoutError) as exc:
                logger.warning("Food provider %s unavailable: %s", provider_source, exc)
            except Exception:
                logger.warning("Food provider %s failed", provider_source, exc_info=True)
            return []

        remote_results = await asyncio.gather(
            *(fetch(source, provider) for source, provider in providers.items()),
            return_exceptions=True,
        )
        provider_foods: list[ProviderFood] = []
        for remote_result in remote_results:
            if isinstance(remote_result, BaseException):
                logger.warning("Food provider search failed: %s", remote_result)
            else:
                provider_foods.extend(remote_result)
        await upsert_provider_foods(
            session,
            provider_foods,
        )
        if provider_foods:
            await session.commit()

    statement = select(Food).where(
        (Food.user_id == user.id) | Food.user_id.is_(None),
        Food.archived_at.is_(None),
        (Food.expires_at.is_(None) | (Food.expires_at > func.now())),
    )
    for term in search_terms(query):
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(Food.search_text.like(f"%{escaped}%", escape="\\"))
    if sources is not None:
        statement = statement.where(Food.source.in_(list(sources)))

    source_priority = case(
        (Food.user_id.is_not(None), 0),
        *(
            (Food.source == source, priority)
            for source, priority in SOURCE_PRIORITY.items()
            if source is not None
        ),
        else_=SOURCE_PRIORITY[None],
    )
    normalized_query = normalize_search_text(query)
    statement = statement.order_by(
        Food.user_id.is_(None),
        source_priority,
        func.similarity(Food.search_text, normalized_query).desc(),
        func.length(Food.name),
        Food.name,
    ).limit(limit)
    db_result = await session.execute(statement)
    return list(db_result.scalars())
