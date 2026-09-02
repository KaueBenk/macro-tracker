import json
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import SessionLocal
from app.main import create_app
from app.models import Entry, Food, Meal
from tests.conftest import create_identity


def _food(name: str, *, source: str | None = None, source_ref: str | None = None) -> Food:
    return Food(
        user_id=None,
        source=source,
        source_ref=source_ref,
        name=name,
        kcal=100,
        protein_g=5,
        carbs_g=15,
        fat_g=2,
    )


@pytest.mark.asyncio
async def test_food_search_uses_source_priority_and_rest_mcp_parity(
    client: AsyncClient,
) -> None:
    _, token = await create_identity("provider-ranking@example.com")
    async with SessionLocal() as session:
        session.add_all(
            [
                _food("Arroz integral TACO", source="taco", source_ref="taco-1"),
                _food("Arroz integral TBCA", source="tbca", source_ref="tbca-1"),
                _food("Arroz integral USDA", source="usda", source_ref="usda-1"),
                _food("Arroz integral OFF", source="off", source_ref="off-1"),
            ]
        )
        await session.commit()
    private = await client.post(
        "/api/foods",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Arroz integral privado",
            "kcal": 110,
            "protein_g": 5,
            "carbs_g": 20,
            "fat_g": 2,
        },
    )
    assert private.status_code == 201
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    rest = await client.get("/api/foods?search=arroz%20integral", headers=headers)
    assert [food["source"] for food in rest.json()] == [None, "taco", "tbca", "usda", "off"]

    test_app = create_app()
    async with test_app.router.lifespan_context(test_app):
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as mcp_client:
            initialize = await mcp_client.post(
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
            mcp = await mcp_client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "search_foods",
                        "arguments": {"query": "arroz integral"},
                    },
                },
            )
    assert mcp.status_code == 200
    mcp_foods = json.loads(mcp.json()["result"]["content"][0]["text"])
    assert [food["name"] for food in mcp_foods] == [food["name"] for food in rest.json()]


@pytest.mark.asyncio
async def test_food_search_similarity_prefers_closest_match(client: AsyncClient) -> None:
    _, token = await create_identity("similarity@example.com")
    async with SessionLocal() as session:
        session.add_all(
            [
                _food("Arroz integral cozido", source="taco", source_ref="taco-long"),
                _food("Arroz integral", source="taco", source_ref="taco-exact"),
            ]
        )
        await session.commit()
    response = await client.get(
        "/api/foods?search=arroz%20integral",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert [food["name"] for food in response.json()] == [
        "Arroz integral",
        "Arroz integral cozido",
    ]


@pytest.mark.asyncio
async def test_food_search_excludes_archived_and_expired_but_entry_resolves(
    client: AsyncClient,
) -> None:
    user, token = await create_identity("archived@example.com")
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        archived = _food("Archived banana", source="taco", source_ref="archived")
        archived.archived_at = now
        expired = _food("Expired banana", source="taco", source_ref="expired")
        expired.expires_at = now - timedelta(seconds=1)
        session.add_all([archived, expired])
        await session.flush()
        entry = Entry(
            user_id=user.id,
            logged_at=now,
            meal=Meal.snack,
            food_id=archived.id,
            quantity_g=100,
            kcal=100,
            protein_g=5,
            carbs_g=15,
            fat_g=2,
        )
        session.add(entry)
        expired_entry = Entry(
            user_id=user.id,
            logged_at=now,
            meal=Meal.snack,
            food_id=expired.id,
            quantity_g=100,
            kcal=100,
            protein_g=5,
            carbs_g=15,
            fat_g=2,
        )
        session.add(expired_entry)
        await session.commit()
        entry_id = entry.id
        expired_entry_id = expired_entry.id
    headers = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/api/foods?search=archived", headers=headers)).json() == []
    assert (await client.get("/api/foods?search=expired", headers=headers)).json() == []
    resolved = await client.get(f"/api/entries/{entry_id}", headers=headers)
    assert resolved.status_code == 200
    assert resolved.json()["food_id"] == str(archived.id)
    expired_resolved = await client.get(f"/api/entries/{expired_entry_id}", headers=headers)
    assert expired_resolved.status_code == 200
    assert expired_resolved.json()["food_id"] == str(expired.id)


@pytest.mark.asyncio
async def test_food_search_filters_sources(client: AsyncClient) -> None:
    _, token = await create_identity("source-filter@example.com")
    async with SessionLocal() as session:
        session.add_all(
            [
                _food("Feijão fonte", source="taco", source_ref="taco-beans"),
                _food("Feijão fonte", source="tbca", source_ref="tbca-beans"),
            ]
        )
        await session.commit()
    response = await client.get(
        "/api/foods",
        params=[("search", "feijao"), ("sources", "tbca")],
        headers={"Authorization": f"Bearer {token}"},
    )
    assert [food["source"] for food in response.json()] == ["tbca"]
