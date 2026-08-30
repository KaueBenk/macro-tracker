from collections.abc import Sequence

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Food, User
from app.providers.registry import SOURCE_PRIORITY
from app.text import normalize_search_text, search_terms


async def search_foods(
    session: AsyncSession,
    *,
    user: User,
    query: str,
    limit: int,
    sources: Sequence[str] | None = None,
) -> list[Food]:
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
    result = await session.execute(statement)
    return list(result.scalars())
