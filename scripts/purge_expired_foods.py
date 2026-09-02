"""Purge expired global provider foods while preserving user-owned foods."""

from __future__ import annotations

import asyncio

from sqlalchemy import delete, func

from app.db import SessionLocal
from app.models import Food


async def purge_expired_foods() -> int:
    async with SessionLocal() as session:
        result = await session.execute(
            delete(Food).where(
                Food.user_id.is_(None),
                Food.expires_at.is_not(None),
                Food.expires_at <= func.now(),
            )
        )
        await session.commit()
        return result.rowcount or 0


async def _run() -> None:
    print(f"Deleted {await purge_expired_foods()} expired foods.")


if __name__ == "__main__":
    asyncio.run(_run())
