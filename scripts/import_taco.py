"""Import the committed TACO dataset as global foods."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TypedDict

from sqlalchemy import select

from app.db import SessionLocal
from app.models import DatasetVersion, Food

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "taco.json"
TACO_ATTRIBUTION = "Tabela Brasileira de Composição de Alimentos (TACO), 4ª edição. NEPA/UNICAMP."
TACO_SOURCE_VERSION = "TACO 4"


class TacoRecord(TypedDict):
    taco_id: str
    name: str
    category: str | None
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float | None


def _records(path: Path) -> list[TacoRecord]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("TACO dataset must be a JSON array")
    records: list[TacoRecord] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("TACO dataset records must be JSON objects")
        records.append(
            TacoRecord(
                taco_id=_string(item, "taco_id"),
                name=_string(item, "name"),
                category=_optional_string(item, "category"),
                kcal=_number(item, "kcal"),
                protein_g=_number(item, "protein_g"),
                carbs_g=_number(item, "carbs_g"),
                fat_g=_number(item, "fat_g"),
                fiber_g=_optional_number(item, "fiber_g"),
            )
        )
    return records


def _string(item: dict[object, object], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"TACO record field {key!r} must be a non-empty string")
    return value


def _optional_string(item: dict[object, object], key: str) -> str | None:
    value = item.get(key)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"TACO record field {key!r} must be a string or null")
    return value


def _number(item: dict[object, object], key: str) -> float:
    value = item.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"TACO record field {key!r} must be a number")
    return float(value)


def _optional_number(item: dict[object, object], key: str) -> float | None:
    value = item.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"TACO record field {key!r} must be a number or null")
    return float(value)


async def import_taco(path: Path = DATA_PATH, dry_run: bool = False) -> tuple[int, int]:
    inserted = 0
    updated = 0
    raw_data = path.read_bytes()
    records = _records(path)
    fetched_at = datetime.now(UTC)
    async with SessionLocal() as session:
        for record in records:
            result = await session.execute(
                select(Food).where(
                    Food.source == "taco",
                    Food.source_ref == record["taco_id"],
                )
            )
            food = result.scalar_one_or_none()
            values = {
                "name": record["name"],
                "category": record["category"],
                "source_version": TACO_SOURCE_VERSION,
                "attribution": TACO_ATTRIBUTION,
                "locale": "pt-BR",
                "fetched_at": fetched_at,
                "kcal": Decimal(str(record["kcal"])),
                "protein_g": Decimal(str(record["protein_g"])),
                "carbs_g": Decimal(str(record["carbs_g"])),
                "fat_g": Decimal(str(record["fat_g"])),
                "fiber_g": (
                    Decimal(str(record["fiber_g"])) if record["fiber_g"] is not None else None
                ),
            }
            if food is None:
                session.add(
                    Food(
                        user_id=None,
                        source="taco",
                        source_ref=record["taco_id"],
                        **values,
                    )
                )
                inserted += 1
            else:
                for key, value in values.items():
                    setattr(food, key, value)
                updated += 1
            await session.flush()
        session.add(
            DatasetVersion(
                source="taco",
                version=TACO_SOURCE_VERSION,
                record_count=len(records),
                checksum=hashlib.sha256(raw_data).hexdigest(),
                notes=str(path),
            )
        )
        if dry_run:
            await session.rollback()
        else:
            await session.commit()
    return inserted, updated


async def _run(path: Path, dry_run: bool) -> None:
    inserted, updated = await import_taco(path, dry_run)
    prefix = "Would import" if dry_run else "Imported"
    print(f"{prefix}: {inserted} inserted, {updated} updated")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--path", type=Path, default=DATA_PATH)
    args = parser.parse_args()
    asyncio.run(_run(args.path, args.dry_run))


if __name__ == "__main__":
    main()
