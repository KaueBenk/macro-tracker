from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.config import get_settings
from app.db import SessionLocal
from app.models import Entry, Meal, User, WebSession
from app.security import hash_token
from app.web.session import WEB_SESSION_COOKIE, csrf_token
from tests.conftest import create_identity


async def create_web_identity(email: str) -> tuple[User, str]:
    raw_token = f"web-session-{email}"
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        user = User(email=email, timezone="America/Sao_Paulo")
        session.add(user)
        await session.flush()
        session.add(
            WebSession(
                user_id=user.id,
                token_hash=hash_token(raw_token),
                created_at=now,
                expires_at=now + timedelta(days=1),
                last_seen_at=now,
            )
        )
        await session.commit()
        return user, raw_token


@pytest.mark.asyncio
async def test_web_cookie_authenticates_api_and_exposes_csrf(client: AsyncClient) -> None:
    user, raw_token = await create_web_identity("api-cookie@example.com")
    async with SessionLocal() as session:
        session.add(
            Entry(
                user_id=user.id,
                logged_at=datetime.now(UTC),
                meal=Meal.lunch,
                description="Cookie entry",
                quantity_g=Decimal("100"),
                kcal=Decimal("500"),
                protein_g=Decimal("25"),
                carbs_g=Decimal("50"),
                fat_g=Decimal("10"),
                fiber_g=Decimal("5"),
            )
        )
        await session.commit()

    client.cookies.set(WEB_SESSION_COOKIE, raw_token)
    summary = await client.get("/api/summary/daily")
    assert summary.status_code == 200
    assert summary.json()["entries_count"] == 1

    session_response = await client.get("/api/session")
    assert session_response.status_code == 200
    assert session_response.json()["user"]["email"] == "api-cookie@example.com"
    assert session_response.json()["csrf_token"] == csrf_token(raw_token, get_settings())


@pytest.mark.asyncio
async def test_web_cookie_requires_csrf_for_mutations(client: AsyncClient) -> None:
    _, raw_token = await create_web_identity("api-csrf@example.com")
    client.cookies.set(WEB_SESSION_COOKIE, raw_token)
    payload = {
        "meal": "breakfast",
        "description": "CSRF entry",
        "kcal": 300,
        "protein_g": 20,
        "carbs_g": 30,
        "fat_g": 8,
    }

    assert (await client.post("/api/entries", json=payload)).status_code == 403
    assert (
        await client.post(
            "/api/entries",
            json=payload,
            headers={"X-CSRF-Token": "wrong"},
        )
    ).status_code == 403
    created = await client.post(
        "/api/entries",
        json=payload,
        headers={"X-CSRF-Token": csrf_token(raw_token, get_settings())},
    )
    assert created.status_code == 201


@pytest.mark.asyncio
async def test_bearer_auth_does_not_require_csrf_and_session_is_null(
    client: AsyncClient,
) -> None:
    _, raw_token = await create_identity("api-bearer@example.com")
    headers = {"Authorization": f"Bearer {raw_token}"}

    assert (await client.get("/api/summary/daily", headers=headers)).status_code == 200
    created = await client.post(
        "/api/entries",
        headers=headers,
        json={
            "meal": "snack",
            "description": "Bearer entry",
            "kcal": 150,
            "protein_g": 10,
            "carbs_g": 20,
            "fat_g": 3,
        },
    )
    assert created.status_code == 201
    session_response = await client.get("/api/session", headers=headers)
    assert session_response.status_code == 200
    assert session_response.json()["csrf_token"] is None


@pytest.mark.asyncio
async def test_api_requires_auth_and_web_cookie_isolation(client: AsyncClient) -> None:
    assert (await client.get("/api/summary/daily")).status_code == 401
    user_a, token_a = await create_web_identity("api-a@example.com")
    user_b, _ = await create_web_identity("api-b@example.com")
    async with SessionLocal() as session:
        session.add(
            Entry(
                user_id=user_b.id,
                logged_at=datetime.now(UTC),
                meal=Meal.dinner,
                description="Private B entry",
                quantity_g=Decimal("100"),
                kcal=Decimal("700"),
                protein_g=Decimal("30"),
                carbs_g=Decimal("60"),
                fat_g=Decimal("20"),
                fiber_g=Decimal("4"),
            )
        )
        await session.commit()

    client.cookies.set(WEB_SESSION_COOKIE, token_a)
    entries = await client.get("/api/entries")
    assert entries.status_code == 200
    assert entries.json() == []
