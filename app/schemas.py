import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.models import Meal

Macro = Annotated[float, Field(ge=0)]


class FoodBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    brand: str | None = None
    category: str | None = None
    kcal: Macro
    protein_g: Macro
    carbs_g: Macro
    fat_g: Macro
    fiber_g: Macro | None = None
    serving_label: str | None = None
    serving_grams: Macro | None = None


class FoodCreate(FoodBase):
    pass


class FoodUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    brand: str | None = None
    category: str | None = None
    kcal: Macro | None = None
    protein_g: Macro | None = None
    carbs_g: Macro | None = None
    fat_g: Macro | None = None
    fiber_g: Macro | None = None
    serving_label: str | None = None
    serving_grams: Macro | None = None


class FoodRead(FoodBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID | None
    source: str | None
    source_ref: str | None
    created_at: datetime
    updated_at: datetime


class EntryBase(BaseModel):
    logged_at: datetime | None = None
    meal: Meal = Meal.other
    food_id: uuid.UUID | None = None
    description: str | None = None
    quantity_g: Macro | None = None
    kcal: Macro | None = None
    protein_g: Macro | None = None
    carbs_g: Macro | None = None
    fat_g: Macro | None = None
    fiber_g: Macro | None = None
    notes: str | None = None


class EntryCreate(EntryBase):
    pass


class EntryUpdate(BaseModel):
    logged_at: datetime | None = None
    meal: Meal | None = None
    food_id: uuid.UUID | None = None
    description: str | None = None
    quantity_g: Macro | None = None
    kcal: Macro | None = None
    protein_g: Macro | None = None
    carbs_g: Macro | None = None
    fat_g: Macro | None = None
    fiber_g: Macro | None = None
    notes: str | None = None


class EntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    logged_at: datetime
    meal: Meal
    food_id: uuid.UUID | None
    description: str | None
    quantity_g: float | None
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class GoalBase(BaseModel):
    effective_from: date
    kcal: Macro
    protein_g: Macro
    carbs_g: Macro
    fat_g: Macro
    fiber_g: Macro | None = None


class GoalCreate(BaseModel):
    effective_from: date | None = None
    kcal: Macro
    protein_g: Macro
    carbs_g: Macro
    fat_g: Macro
    fiber_g: Macro | None = None


class GoalRead(GoalBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class Totals(BaseModel):
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float


class Progress(BaseModel):
    consumed: Totals
    goal: Totals | None
    remaining: Totals | None
    percent: Totals


class DailySummary(Progress):
    date: date
    entries_count: int
    by_meal: dict[str, Totals]


class RangeSummary(BaseModel):
    days: list[DailySummary]
    averages: Totals


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    timezone: str


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timezone: str
