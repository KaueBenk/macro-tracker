from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.db import SessionLocal
from app.models import Entry, Food, Meal
from tests.conftest import create_identity


@pytest.mark.asyncio
async def test_top_foods_aggregates_sorts_limits_and_isolates_users(
    client: AsyncClient,
) -> None:
    user_a, token_a = await create_identity("insights-a@example.com")
    user_b, token_b = await create_identity("insights-b@example.com")
    async with SessionLocal() as session:
        food = Food(
            user_id=user_a.id,
            name="Arroz integral",
            kcal=Decimal("130"),
            protein_g=Decimal("3"),
            carbs_g=Decimal("28"),
            fat_g=Decimal("1"),
            fiber_g=Decimal("2"),
        )
        session.add(food)
        await session.flush()
        session.add_all(
            [
                Entry(
                    user_id=user_a.id,
                    logged_at=datetime(2025, 1, 1, 12, tzinfo=UTC),
                    meal=Meal.lunch,
                    food_id=food.id,
                    quantity_g=Decimal("150"),
                    kcal=Decimal("300"),
                    protein_g=Decimal("7"),
                    carbs_g=Decimal("40"),
                    fat_g=Decimal("3"),
                ),
                Entry(
                    user_id=user_a.id,
                    logged_at=datetime(2025, 1, 2, 12, tzinfo=UTC),
                    meal=Meal.dinner,
                    food_id=food.id,
                    quantity_g=Decimal("100"),
                    kcal=Decimal("120"),
                    protein_g=Decimal("4"),
                    carbs_g=Decimal("20"),
                    fat_g=Decimal("2"),
                ),
                Entry(
                    user_id=user_a.id,
                    logged_at=datetime(2025, 1, 1, 13, tzinfo=UTC),
                    meal=Meal.snack,
                    description="Protein Shake",
                    kcal=Decimal("80"),
                    protein_g=Decimal("20"),
                    carbs_g=Decimal("3"),
                    fat_g=Decimal("1"),
                ),
                Entry(
                    user_id=user_a.id,
                    logged_at=datetime(2025, 1, 2, 13, tzinfo=UTC),
                    meal=Meal.snack,
                    description=" protein shake ",
                    kcal=Decimal("70"),
                    protein_g=Decimal("18"),
                    carbs_g=Decimal("2"),
                    fat_g=Decimal("1"),
                ),
                Entry(
                    user_id=user_a.id,
                    logged_at=datetime(2025, 1, 3, 12, tzinfo=UTC),
                    meal=Meal.lunch,
                    food_id=food.id,
                    quantity_g=Decimal("100"),
                    kcal=Decimal("900"),
                    protein_g=Decimal("10"),
                    carbs_g=Decimal("10"),
                    fat_g=Decimal("10"),
                ),
                Entry(
                    user_id=user_b.id,
                    logged_at=datetime(2025, 1, 1, 12, tzinfo=UTC),
                    meal=Meal.lunch,
                    description="Protein Shake",
                    kcal=Decimal("999"),
                    protein_g=Decimal("1"),
                    carbs_g=Decimal("1"),
                    fat_g=Decimal("1"),
                ),
            ]
        )
        await session.commit()

    headers_a = {"Authorization": f"Bearer {token_a}"}
    response = await client.get(
        "/api/insights/top-foods",
        params={"from": "2025-01-01", "to": "2025-01-02", "limit": 10},
        headers=headers_a,
    )
    assert response.status_code == 200
    foods = response.json()
    assert [food["label"] for food in foods] == ["Arroz integral", "Protein Shake"]
    assert foods[0] == {
        "food_id": str(food.id),
        "label": "Arroz integral",
        "entries": 2,
        "total_kcal": 420.0,
        "total_protein_g": 11.0,
        "total_quantity_g": 250.0,
        "avg_kcal": 210.0,
    }
    assert foods[1]["food_id"] is None
    assert foods[1]["entries"] == 2
    assert foods[1]["total_kcal"] == 150.0
    assert foods[1]["total_quantity_g"] is None
    assert foods[1]["avg_kcal"] == 75.0

    limited = await client.get(
        "/api/insights/top-foods",
        params={"from": "2025-01-01", "to": "2025-01-02", "limit": 1},
        headers=headers_a,
    )
    assert [food["label"] for food in limited.json()] == ["Arroz integral"]

    headers_b = {"Authorization": f"Bearer {token_b}"}
    isolated = await client.get(
        "/api/insights/top-foods",
        params={"from": "2025-01-01", "to": "2025-01-02"},
        headers=headers_b,
    )
    assert isolated.status_code == 200
    assert isolated.json()[0]["total_kcal"] == 999.0
