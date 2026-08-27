import hashlib
import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.db import SessionLocal, engine
from app.main import app
from app.models import ApiToken, Entry, Food, Goal, User


@pytest_asyncio.fixture(autouse=True)
async def clean_database() -> AsyncIterator[None]:
    await engine.dispose()
    async with SessionLocal() as session:
        await session.execute(delete(Entry))
        await session.execute(delete(Goal))
        await session.execute(delete(Food))
        await session.execute(delete(ApiToken))
        await session.execute(delete(User))
        await session.commit()
    yield
    async with SessionLocal() as session:
        await session.execute(delete(Entry))
        await session.execute(delete(Goal))
        await session.execute(delete(Food))
        await session.execute(delete(ApiToken))
        await session.execute(delete(User))
        await session.commit()
    await engine.dispose()


async def create_identity(email: str, timezone_name: str = "America/Sao_Paulo") -> tuple[User, str]:
    raw_token = f"test-token-{uuid.uuid4()}"
    async with SessionLocal() as session:
        user = User(email=email, timezone=timezone_name)
        session.add(user)
        await session.flush()
        session.add(
            ApiToken(
                user_id=user.id,
                name="test",
                token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            )
        )
        await session.commit()
        return user, raw_token


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        yield test_client
