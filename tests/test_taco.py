import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Food
from app.text import search_terms
from scripts.import_taco import import_taco


def test_search_terms_normalizes_accents_and_empty_tokens() -> None:
    assert search_terms("  arroz   integral ") == ["arroz", "integral"]
    assert search_terms("Feijão") == ["feijao"]


@pytest.mark.asyncio
async def test_taco_import_is_idempotent_and_updates_existing_rows(tmp_path: Path) -> None:
    dataset = tmp_path / "taco.json"
    records = [
        {
            "taco_id": "1",
            "name": "Feijão, carioca, cozido",
            "category": "Leguminosas",
            "kcal": 76,
            "protein_g": 4.8,
            "carbs_g": 13.6,
            "fat_g": 0.5,
            "fiber_g": 8.5,
        },
        {
            "taco_id": "2",
            "name": "Arroz, integral, cozido",
            "category": "Cereais",
            "kcal": 123,
            "protein_g": 2.6,
            "carbs_g": 25.8,
            "fat_g": 1,
            "fiber_g": 2.7,
        },
    ]
    dataset.write_text(json.dumps(records), encoding="utf-8")

    assert await import_taco(dataset) == (2, 0)
    records[0]["kcal"] = 80
    dataset.write_text(json.dumps(records), encoding="utf-8")
    assert await import_taco(dataset) == (0, 2)

    async with SessionLocal() as session:
        result = await session.execute(select(Food).where(Food.source == "taco"))
        foods = list(result.scalars())
    assert len(foods) == 2
    assert next(food for food in foods if food.source_ref == "1").kcal == 80
