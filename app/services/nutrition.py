from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from app.models import Entry, Food, Goal


@dataclass(frozen=True)
class MacroValues:
    kcal: float | None
    protein_g: float | None
    carbs_g: float | None
    fat_g: float | None
    fiber_g: float | None


def rounded(value: float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def resolve_entry_macros(
    food: Food | None,
    quantity_g: float | None,
    overrides: MacroValues,
) -> MacroValues:
    calculated: dict[str, float | None] = {}
    if food is not None and quantity_g is not None:
        ratio = quantity_g / 100
        calculated = {
            "kcal": float(food.kcal) * ratio,
            "protein_g": float(food.protein_g) * ratio,
            "carbs_g": float(food.carbs_g) * ratio,
            "fat_g": float(food.fat_g) * ratio,
            "fiber_g": float(food.fiber_g) * ratio if food.fiber_g is not None else None,
        }
    values = {
        "kcal": overrides.kcal if overrides.kcal is not None else calculated.get("kcal"),
        "protein_g": overrides.protein_g
        if overrides.protein_g is not None
        else calculated.get("protein_g"),
        "carbs_g": overrides.carbs_g
        if overrides.carbs_g is not None
        else calculated.get("carbs_g"),
        "fat_g": overrides.fat_g if overrides.fat_g is not None else calculated.get("fat_g"),
        "fiber_g": overrides.fiber_g
        if overrides.fiber_g is not None
        else calculated.get("fiber_g"),
    }
    required = ("kcal", "protein_g", "carbs_g", "fat_g")
    if any(values[key] is None for key in required):
        raise ValueError(
            "food and quantity_g or explicit kcal, protein_g, carbs_g, and fat_g are required"
        )
    return MacroValues(
        kcal=float(rounded(values["kcal"] or 0)),
        protein_g=float(rounded(values["protein_g"] or 0)),
        carbs_g=float(rounded(values["carbs_g"] or 0)),
        fat_g=float(rounded(values["fat_g"] or 0)),
        fiber_g=float(rounded(values["fiber_g"])) if values["fiber_g"] is not None else None,
    )


def day_bounds(day: date, timezone_name: str) -> tuple[datetime, datetime]:
    local_zone = ZoneInfo(timezone_name)
    start_local = datetime.combine(day, time.min, tzinfo=local_zone)
    end_local = datetime.combine(day, time.max, tzinfo=local_zone)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def totals(entries: Iterable[Entry]) -> MacroValues:
    values = list(entries)
    return MacroValues(
        kcal=round(sum(float(entry.kcal) for entry in values), 2),
        protein_g=round(sum(float(entry.protein_g) for entry in values), 2),
        carbs_g=round(sum(float(entry.carbs_g) for entry in values), 2),
        fat_g=round(sum(float(entry.fat_g) for entry in values), 2),
        fiber_g=round(sum(float(entry.fiber_g or 0) for entry in values), 2),
    )


def effective_goal(goals: Iterable[Goal], day: date) -> Goal | None:
    candidates = [goal for goal in goals if goal.effective_from <= day]
    if not candidates:
        return None
    return max(candidates, key=lambda goal: goal.effective_from)
