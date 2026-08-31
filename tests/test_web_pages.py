from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import Entry, Food, User, WebSession
from app.security import hash_token
from app.web.auth import WEB_SESSION_COOKIE, _csrf_token


async def _web_client() -> tuple[AsyncClient, User, str]:
    raw_token = "web-page-test-token"
    async with SessionLocal() as session:
        user = User(email="pages@example.com", timezone="America/Sao_Paulo")
        session.add(user)
        await session.flush()
        session.add(
            WebSession(
                user_id=user.id,
                token_hash=hash_token(raw_token),
                created_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=1),
                last_seen_at=datetime.now(UTC),
            )
        )
        await session.commit()
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    client.cookies.set(WEB_SESSION_COOKIE, raw_token)
    return client, user, raw_token


@pytest.mark.asyncio
async def test_web_pages_require_session_and_render() -> None:
    paths = [
        "/app",
        "/app/adicionar",
        "/app/alimentos",
        "/app/metas",
        "/app/historico",
        "/app/conta",
    ]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anonymous:
        for path in paths:
            response = await anonymous.get(path, follow_redirects=False)
            assert response.status_code == 302
            assert response.headers["location"].startswith("/web/login")

    client, _, _ = await _web_client()
    async with client:
        for path in paths:
            response = await client.get(path)
            assert response.status_code == 200
        assert "Macro Tracker" in (await client.get("/app")).text


@pytest.mark.asyncio
async def test_create_goal_entry_and_delete_entry_from_web() -> None:
    client, user, raw_token = await _web_client()
    csrf = _csrf_token(raw_token, get_settings())
    async with client:
        goal = await client.post(
            "/app/metas",
            data={
                "csrf_token": csrf,
                "kcal": "2000",
                "protein_g": "100",
                "carbs_g": "200",
                "fat_g": "60",
                "fiber_g": "30",
                "effective_from": "2026-01-01",
            },
            follow_redirects=False,
        )
        assert goal.status_code == 303
        entry = await client.post(
            "/app/entradas",
            data={
                "csrf_token": csrf,
                "description": "Lanche manual",
                "kcal": "123,5",
                "protein_g": "10",
                "carbs_g": "12",
                "fat_g": "4",
                "fiber_g": "2",
                "meal": "snack",
            },
            follow_redirects=False,
        )
        assert entry.status_code == 303
        day = await client.get("/app")
        assert "Lanche manual" in day.text
        assert "123.50" in day.text or "123.5" in day.text
        async with SessionLocal() as session:
            stored = await session.scalar(select(Entry).where(Entry.user_id == user.id))
            assert stored is not None
            entry_id = stored.id
        deleted = await client.post(
            f"/app/entradas/{entry_id}/excluir",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        assert deleted.status_code == 303
    async with SessionLocal() as session:
        assert await session.scalar(select(Entry).where(Entry.id == entry_id)) is None


@pytest.mark.asyncio
async def test_food_search_and_external_attribution_are_rendered() -> None:
    client, _, raw_token = await _web_client()
    csrf = _csrf_token(raw_token, get_settings())
    async with SessionLocal() as session:
        session.add(
            Food(
                user_id=None,
                name="Alimento global de teste",
                brand=None,
                category=None,
                kcal=Decimal("100"),
                protein_g=Decimal("5"),
                carbs_g=Decimal("10"),
                fat_g=Decimal("2"),
                fiber_g=None,
                source="off",
                source_ref="123",
                attribution="Atribuição de teste",
            )
        )
        await session.commit()
    async with client:
        response = await client.get("/app/adicionar", params={"q": "global"})
        assert response.status_code == 200
        assert "Atribuição de teste" in response.text
        missing_csrf = await client.post("/app/metas", data={"kcal": "1"})
        assert missing_csrf.status_code == 403
        global_food = await client.get("/app/alimentos", params={"q": "global"})
        assert "somente leitura" in global_food.text
        async with SessionLocal() as session:
            food = await session.scalar(select(Food).where(Food.name == "Alimento global de teste"))
            assert food is not None
            food_id = food.id
        forbidden = await client.post(
            f"/app/alimentos/{food_id}/excluir",
            data={"csrf_token": csrf},
        )
        assert forbidden.status_code == 403


@pytest.mark.asyncio
async def test_remote_food_search_renders_attribution(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, _ = await _web_client()

    async def fake_search(*args: object, **kwargs: object) -> list[Food]:
        return [
            Food(
                name="Resultado remoto",
                brand="Fonte",
                kcal=Decimal("80"),
                protein_g=Decimal("4"),
                carbs_g=Decimal("8"),
                fat_g=Decimal("1"),
                attribution="Atribuição remota",
                source="off",
            )
        ]

    monkeypatch.setattr("app.web.pages.food_search.search_foods", fake_search)
    async with client:
        response = await client.get("/app/adicionar", params={"q": "remoto", "remote": "true"})
    assert response.status_code == 200
    assert "Atribuição remota" in response.text


@pytest.mark.asyncio
async def test_invalid_dates_and_periods_do_not_fail() -> None:
    client, _, _ = await _web_client()
    async with client:
        day = await client.get("/app", params={"d": "not-a-date"})
        history = await client.get("/app/historico", params={"dias": "90"})
    assert day.status_code == 200
    assert "Data inválida" in day.text
    assert history.status_code == 200
    assert "últimos 7 dias" in history.text


@pytest.mark.asyncio
async def test_development_login_creates_visual_session() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/web/dev-login", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/app"
        assert WEB_SESSION_COOKIE in response.cookies
        page = await client.get("/app/conta")
    assert page.status_code == 200
    assert "visual@example.com" in page.text
