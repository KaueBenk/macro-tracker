from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.models import Food, Goal
from app.services.nutrition import MacroValues, effective_goal, resolve_entry_macros
from tests.conftest import create_identity


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
    next_day = await client.get("/api/summary/daily?date=2025-01-02", headers=headers)
    assert next_day.json()["entries_count"] == 0


def test_effective_goal_selection() -> None:
    first = Goal(effective_from=date(2025, 1, 1), kcal=1, protein_g=1, carbs_g=1, fat_g=1)
    second = Goal(effective_from=date(2025, 1, 3), kcal=2, protein_g=2, carbs_g=2, fat_g=2)
    assert effective_goal([first, second], date(2025, 1, 2)) is first
