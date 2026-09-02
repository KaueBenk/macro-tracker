from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings
from app.db import SessionLocal
from app.main import app
from app.models import Food, Goal
from app.services.nutrition import MacroValues, effective_goal, resolve_entry_macros
from app.text import normalize_search_text
from tests.conftest import create_identity


def test_neon_database_url_normalizes_for_asyncpg() -> None:
    neon_url = (
        "postgresql://user:pass@ep-xxx-pooler.region.aws.neon.tech/neondb"
        "?sslmode=require&channel_binding=require"
    )
    settings = Settings(database_url=neon_url)
    assert (
        settings.database_url
        == "postgresql+asyncpg://user:pass@ep-xxx-pooler.region.aws.neon.tech/neondb?ssl=require"
    )
    engine = create_async_engine(settings.database_url)
    try:
        _, connect_args = engine.dialect.create_connect_args(make_url(settings.database_url))
    finally:
        engine.sync_engine.dispose()
    assert connect_args["ssl"] == "require"
    assert "sslmode" not in connect_args


def test_postgres_database_url_gets_asyncpg_driver() -> None:
    settings = Settings(database_url="postgres://user:pass@localhost/db")
    assert settings.database_url == "postgresql+asyncpg://user:pass@localhost/db"


def test_asyncpg_database_url_passes_through_unchanged() -> None:
    value = "postgresql+asyncpg://user:pass@localhost/db"
    assert Settings(database_url=value).database_url == value


def test_database_url_preserves_unrelated_query_parameters() -> None:
    settings = Settings(
        database_url="postgresql://user:pass@localhost/db?application_name=macro-tracker"
    )
    parsed = make_url(settings.database_url)
    assert parsed.drivername == "postgresql+asyncpg"
    assert parsed.query["application_name"] == "macro-tracker"


def test_macro_resolution_rounds_and_honors_overrides() -> None:
    food = Food(
        name="Oats",
        kcal=Decimal("389"),
        protein_g=Decimal("16.9"),
        carbs_g=Decimal("66.3"),
        fat_g=Decimal("6.9"),
        fiber_g=Decimal("10.6"),
    )
    resolved = resolve_entry_macros(
        food,
        37,
        MacroValues(kcal=None, protein_g=20, carbs_g=None, fat_g=None, fiber_g=None),
    )
    assert resolved.kcal == 143.93
    assert resolved.protein_g == 20
    assert resolved.carbs_g == 24.53


def test_macro_resolution_requires_macros() -> None:
    with pytest.raises(ValueError):
        resolve_entry_macros(None, None, MacroValues(None, None, None, None, None))


@pytest.mark.asyncio
async def test_auth_missing_and_invalid(client: AsyncClient) -> None:
    assert (await client.get("/api/foods")).status_code == 401
    assert (
        await client.get("/api/foods", headers={"Authorization": "Bearer wrong"})
    ).status_code == 401


@pytest.mark.asyncio
async def test_food_and_entry_crud_and_scope(client: AsyncClient) -> None:
    _, token_a = await create_identity("a@example.com")
    _, token_b = await create_identity("b@example.com")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}
    food_response = await client.post(
        "/api/foods",
        headers=headers_a,
        json={"name": "Rice", "kcal": 130, "protein_g": 2.7, "carbs_g": 28, "fat_g": 0.3},
    )
    assert food_response.status_code == 201
    food_id = food_response.json()["id"]
    assert (
        await client.patch(f"/api/foods/{food_id}", headers=headers_b, json={"name": "Nope"})
    ).status_code == 404
    assert (await client.delete(f"/api/foods/{food_id}", headers=headers_b)).status_code == 404
    entry_response = await client.post(
        "/api/entries",
        headers=headers_a,
        json={"food_id": food_id, "quantity_g": 200, "meal": "lunch"},
    )
    assert entry_response.status_code == 201
    assert entry_response.json()["kcal"] == 260.0
    entry_id = entry_response.json()["id"]
    assert (await client.get(f"/api/entries/{entry_id}", headers=headers_b)).status_code == 404
    assert (
        await client.patch(f"/api/entries/{entry_id}", headers=headers_b, json={"notes": "x"})
    ).status_code == 404
    assert (await client.delete(f"/api/entries/{entry_id}", headers=headers_b)).status_code == 404
    assert (
        await client.patch(f"/api/entries/{entry_id}", headers=headers_a, json={"notes": "updated"})
    ).status_code == 200
    assert (await client.delete(f"/api/entries/{entry_id}", headers=headers_a)).status_code == 204


@pytest.mark.asyncio
async def test_goal_history_and_daily_summary_with_and_without_goal(client: AsyncClient) -> None:
    _, token = await create_identity("goal@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    no_goal = await client.get("/api/summary/daily?date=2025-01-01", headers=headers)
    assert no_goal.status_code == 200
    assert no_goal.json()["goal"] is None
    await client.put(
        "/api/goals",
        headers=headers,
        json={
            "effective_from": "2025-01-01",
            "kcal": 1800,
            "protein_g": 100,
            "carbs_g": 200,
            "fat_g": 60,
        },
    )
    await client.put(
        "/api/goals",
        headers=headers,
        json={
            "effective_from": "2025-01-03",
            "kcal": 2000,
            "protein_g": 120,
            "carbs_g": 220,
            "fat_g": 70,
        },
    )
    current = await client.get("/api/goals/current?date=2025-01-02", headers=headers)
    assert current.json()["kcal"] == 1800
    await client.post(
        "/api/entries",
        headers=headers,
        json={
            "logged_at": "2025-01-02T02:30:00Z",
            "meal": "snack",
            "kcal": 500,
            "protein_g": 30,
            "carbs_g": 50,
            "fat_g": 10,
        },
    )
    summary = await client.get("/api/summary/daily?date=2025-01-01", headers=headers)
    assert summary.json()["entries_count"] == 1
    assert summary.json()["consumed"]["kcal"] == 500
    assert summary.json()["remaining"]["kcal"] == 1300
    assert summary.json()["percent"]["kcal"] == 27.8
    assert summary.json()["remaining"]["fiber_g"] == 0
    assert summary.json()["percent"]["fiber_g"] == 0
    next_day = await client.get("/api/summary/daily?date=2025-01-02", headers=headers)
    assert next_day.json()["entries_count"] == 0


def test_effective_goal_selection() -> None:
    first = Goal(effective_from=date(2025, 1, 1), kcal=1, protein_g=1, carbs_g=1, fat_g=1)
    second = Goal(effective_from=date(2025, 1, 3), kcal=2, protein_g=2, carbs_g=2, fat_g=2)
    assert effective_goal([first, second], date(2025, 1, 2)) is first


@pytest.mark.asyncio
async def test_range_summary_has_daily_totals_and_averages(client: AsyncClient) -> None:
    _, token = await create_identity("range@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    await client.post(
        "/api/entries",
        headers=headers,
        json={
            "logged_at": "2025-01-01T12:00:00Z",
            "meal": "lunch",
            "kcal": 500,
            "protein_g": 25,
            "carbs_g": 50,
            "fat_g": 10,
        },
    )
    await client.post(
        "/api/entries",
        headers=headers,
        json={
            "logged_at": "2025-01-02T12:00:00Z",
            "meal": "dinner",
            "kcal": 700,
            "protein_g": 35,
            "carbs_g": 70,
            "fat_g": 14,
        },
    )
    response = await client.get("/api/summary/range?from=2025-01-01&to=2025-01-02", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert [day["consumed"]["kcal"] for day in payload["days"]] == [500.0, 700.0]
    assert payload["days"][0]["entries_count"] == 1
    assert payload["days"][1]["consumed"]["protein_g"] == 35.0
    assert payload["averages"] == {
        "kcal": 600.0,
        "protein_g": 30.0,
        "carbs_g": 60.0,
        "fat_g": 12.0,
        "fiber_g": 0.0,
    }


@pytest.mark.asyncio
async def test_global_food_search_is_visible_but_private_food_is_scoped(
    client: AsyncClient,
) -> None:
    _, token_a = await create_identity("foods-a@example.com")
    _, token_b = await create_identity("foods-b@example.com")
    async with SessionLocal() as session:
        global_food = Food(
            user_id=None,
            name="Global quinoa",
            kcal=120,
            protein_g=4,
            carbs_g=21,
            fat_g=2,
        )
        session.add(global_food)
        await session.commit()
    private_response = await client.post(
        "/api/foods",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Private quinoa", "kcal": 130, "protein_g": 5, "carbs_g": 20, "fat_g": 3},
    )
    assert private_response.status_code == 201
    response = await client.get(
        "/api/foods?search=quinoa", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert response.status_code == 200
    names = {food["name"] for food in response.json()}
    assert names == {"Global quinoa"}


def test_normalize_search_text_removes_accents_and_collapses_spaces() -> None:
    assert normalize_search_text("  Feijão ", None, "CARIOCA", "  cozido  ") == (
        "feijao carioca cozido"
    )


@pytest.mark.asyncio
async def test_food_search_supports_accent_free_multi_token_queries(
    client: AsyncClient,
) -> None:
    _, token = await create_identity("search@example.com")
    async with SessionLocal() as session:
        session.add_all(
            [
                Food(
                    user_id=None,
                    name="Feijão, carioca, cozido",
                    kcal=76,
                    protein_g=4.8,
                    carbs_g=13.6,
                    fat_g=0.5,
                ),
                Food(
                    user_id=None,
                    name="Arroz, integral, cozido",
                    kcal=123,
                    protein_g=2.6,
                    carbs_g=25.8,
                    fat_g=1,
                ),
                Food(
                    user_id=None,
                    name="Arroz branco cozido",
                    kcal=128,
                    protein_g=2.5,
                    carbs_g=28.1,
                    fat_g=0.2,
                ),
            ]
        )
        await session.commit()
    headers = {"Authorization": f"Bearer {token}"}
    bean = await client.get("/api/foods?search=feijao", headers=headers)
    assert [food["name"] for food in bean.json()] == ["Feijão, carioca, cozido"]
    rice = await client.get("/api/foods?search=arroz%20integral", headers=headers)
    assert [food["name"] for food in rice.json()] == ["Arroz, integral, cozido"]


@pytest.mark.asyncio
async def test_private_food_precedes_global_food_with_same_name(client: AsyncClient) -> None:
    _, token = await create_identity("ordering@example.com")
    async with SessionLocal() as session:
        session.add(
            Food(
                user_id=None,
                name="Ovo cozido",
                kcal=155,
                protein_g=13,
                carbs_g=1,
                fat_g=11,
            )
        )
        await session.commit()
    private = await client.post(
        "/api/foods",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Ovo cozido", "kcal": 160, "protein_g": 14, "carbs_g": 1, "fat_g": 12},
    )
    assert private.status_code == 201
    response = await client.get(
        "/api/foods?search=ovo", headers={"Authorization": f"Bearer {token}"}
    )
    assert [food["user_id"] for food in response.json()] == [
        private.json()["user_id"],
        None,
    ]


@pytest.mark.asyncio
async def test_food_search_text_updates_after_patch(client: AsyncClient) -> None:
    _, token = await create_identity("search-update@example.com")
    created = await client.post(
        "/api/foods",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Batata",
            "category": "Tubérculos",
            "kcal": 80,
            "protein_g": 2,
            "carbs_g": 18,
            "fat_g": 0,
        },
    )
    food_id = created.json()["id"]
    updated = await client.patch(
        f"/api/foods/{food_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Batata doce", "category": "Raízes doces"},
    )
    assert updated.status_code == 200
    assert updated.json()["category"] == "Raízes doces"
    sweet = await client.get("/api/foods?search=doce", headers={"Authorization": f"Bearer {token}"})
    assert [food["name"] for food in sweet.json()] == ["Batata doce"]
    category = await client.get(
        "/api/foods?search=raizes doces",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert [food["name"] for food in category.json()] == ["Batata doce"]
    old = await client.get("/api/foods?search=batata", headers={"Authorization": f"Bearer {token}"})
    assert [food["name"] for food in old.json()] == ["Batata doce"]


@pytest.mark.asyncio
async def test_mcp_lists_tools_and_scopes_entries(client: AsyncClient) -> None:
    _, token_a = await create_identity("mcp-a@example.com")
    _, token_b = await create_identity("mcp-b@example.com")
    headers = {
        "Authorization": f"Bearer {token_a}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    async with app.router.lifespan_context(app):
        assert (await client.get("/nope")).status_code == 404
        initialize = await client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "1.0"},
                },
            },
        )
        assert initialize.status_code == 200
        trailing_initialize = await client.post(
            "/mcp/",
            headers={
                **headers,
                "Authorization": f"Bearer {token_a}",
            },
            json={
                "jsonrpc": "2.0",
                "id": 10,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "1.0"},
                },
            },
        )
        assert trailing_initialize.status_code == 200
        listed = await client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert listed.status_code == 200
        tool_names = {tool["name"] for tool in listed.json()["result"]["tools"]}
        assert tool_names == {
            "log_food_entry",
            "list_entries",
            "delete_entry",
            "search_foods",
            "lookup_food_barcode",
            "create_food",
            "set_daily_goal",
            "get_daily_progress",
            "get_range_summary",
        }
        called = await client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "log_food_entry",
                    "arguments": {
                        "logged_at": "2025-01-02T12:00:00Z",
                        "meal": "lunch",
                        "kcal": 450,
                        "protein_g": 30,
                        "carbs_g": 40,
                        "fat_g": 10,
                    },
                },
            },
        )
        assert called.status_code == 200
        result_text = called.json()["result"]["content"][0]["text"]
        assert '"kcal": 450.0' in result_text
        goal_call = await client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "set_daily_goal",
                    "arguments": {
                        "effective_from": "2025-01-02",
                        "kcal": 2000,
                        "protein_g": 100,
                        "carbs_g": 200,
                        "fat_g": 60,
                    },
                },
            },
        )
        assert goal_call.status_code == 200
        assert '"effective_from": "2025-01-02"' in goal_call.json()["result"]["content"][0]["text"]
        progress_call = await client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "get_daily_progress",
                    "arguments": {"date": "2025-01-02"},
                },
            },
        )
        assert progress_call.status_code == 200
        progress_text = progress_call.json()["result"]["content"][0]["text"]
        assert '"kcal": 450.0' in progress_text
        assert '"kcal": 2000.0' in progress_text
        assert '"kcal": 1550.0' in progress_text
        assert '"fiber_g": 0.0' in progress_text
        foreign = await client.post(
            "/mcp",
            headers={
                **headers,
                "Authorization": f"Bearer {token_b}",
            },
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "list_entries",
                    "arguments": {"date": "2025-01-02"},
                },
            },
        )
        assert foreign.status_code == 200
        assert foreign.json()["result"]["content"][0]["text"] == "[]"


@pytest.mark.asyncio
async def test_mcp_requires_bearer_token(client: AsyncClient) -> None:
    response = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert response.status_code == 401
    invalid = await client.post(
        "/mcp",
        headers={"Authorization": "Bearer invalid"},
        json={"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}},
    )
    assert invalid.status_code == 401


def test_serverless_defaults_to_vercel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("SERVERLESS", raising=False)
    assert Settings().serverless is True
    monkeypatch.setenv("SERVERLESS", "false")
    assert Settings().serverless is False
