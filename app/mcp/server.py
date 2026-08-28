from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from mcp.server.auth.routes import build_resource_metadata_url
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.applications import Starlette
from starlette.types import ASGIApp

from app.config import get_auth_settings
from app.db import SessionLocal
from app.mcp.auth import BearerAuthMiddleware, MCPPathAdapter, current_user_id
from app.models import Entry, Food, Goal, Meal, User
from app.oauth.provider import DbOAuthProvider
from app.oauth.verifier import CompositeTokenVerifier
from app.routers.summary import make_daily_summary
from app.schemas import EntryRead, FoodRead, GoalRead
from app.services.nutrition import MacroValues, day_bounds, resolve_entry_macros

oauth_provider = DbOAuthProvider()
token_verifier = CompositeTokenVerifier(oauth_provider)

server = MCPServer(
    name="macro-tracker",
    version="0.1.0",
    instructions="Track calories and macronutrients for the authenticated user.",
    auth=get_auth_settings(),
    token_verifier=token_verifier,
)

LoggedAtInput = Annotated[
    str | None,
    Field(
        description=(
            "Timestamp in ISO-8601 format; absent means now in the user's timezone. Stored in UTC."
        )
    ),
]
MacroInput = Annotated[float | None, Field(ge=0, description="Macro quantity in grams.")]
KcalInput = Annotated[float | None, Field(ge=0, description="Calories.")]
FoodIdInput = Annotated[
    UUID | None,
    Field(description="Food UUID; private foods must belong to the authenticated user."),
]
MealInput = Annotated[
    Meal,
    Field(description="Meal category: breakfast, lunch, dinner, snack, or other."),
]


def _json(value: object) -> str:
    return json.dumps(value, default=str, ensure_ascii=False)


async def _user(session: AsyncSession) -> User | None:
    user_id = current_user_id.get()
    if user_id is None:
        return None
    return await session.get(User, user_id)


def _parse_date(value: str | None, user: User) -> date:
    return (
        datetime.now(ZoneInfo(user.timezone)).date() if value is None else date.fromisoformat(value)
    )


def _parse_logged_at(value: str | None, user: User) -> datetime:
    if value is None:
        return datetime.now(ZoneInfo(user.timezone)).astimezone(UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(user.timezone))
    return parsed.astimezone(UTC)


def _entry_output(entry: Entry) -> dict[str, object]:
    return EntryRead.model_validate(entry).model_dump(mode="json")


@server.tool()
async def log_food_entry(
    description: Annotated[
        str | None, Field(description="Optional free-text description of the food entry.")
    ] = None,
    food_id: FoodIdInput = None,
    quantity_g: Annotated[float | None, Field(ge=0, description="Food quantity in grams.")] = None,
    meal: MealInput = Meal.other,
    logged_at: LoggedAtInput = None,
    kcal: KcalInput = None,
    protein_g: MacroInput = None,
    carbs_g: MacroInput = None,
    fat_g: MacroInput = None,
    fiber_g: MacroInput = None,
    notes: Annotated[str | None, Field(description="Optional notes.")] = None,
) -> str:
    """Create a food entry and return it with progress for that local day.

    Foods use nutrition values per 100 g. Explicit macro values are in grams,
    except kcal; when food_id and quantity_g are provided, calculated values are
    used unless an explicit macro override is supplied.
    """
    async with SessionLocal() as session:
        user = await _user(session)
        if user is None:
            return "Error: authenticated user was not found."
        try:
            food: Food | None = None
            if food_id is not None:
                result = await session.execute(
                    select(Food).where(
                        Food.id == food_id,
                        (Food.user_id == user.id) | Food.user_id.is_(None),
                    )
                )
                food = result.scalar_one_or_none()
                if food is None:
                    return "Error: food was not found or is not visible to this user."
            macros = resolve_entry_macros(
                food,
                quantity_g,
                MacroValues(kcal, protein_g, carbs_g, fat_g, fiber_g),
            )
            logged = _parse_logged_at(logged_at, user)
            entry = Entry(
                user_id=user.id,
                logged_at=logged,
                meal=meal,
                food_id=food_id,
                description=description,
                quantity_g=quantity_g,
                kcal=Decimal(str(macros.kcal)),
                protein_g=Decimal(str(macros.protein_g)),
                carbs_g=Decimal(str(macros.carbs_g)),
                fat_g=Decimal(str(macros.fat_g)),
                fiber_g=Decimal(str(macros.fiber_g)) if macros.fiber_g is not None else None,
                notes=notes,
            )
            session.add(entry)
            await session.commit()
            await session.refresh(entry)
            target_day = logged.astimezone(ZoneInfo(user.timezone)).date()
            summary = await _daily_summary(target_day, user, session)
            return _json({"entry": _entry_output(entry), "daily_progress": summary})
        except (ValueError, TypeError) as exc:
            await session.rollback()
            return f"Error: invalid entry data ({exc})."
        except Exception:
            await session.rollback()
            return "Error: could not create the food entry."


async def _daily_summary(target: date, user: User, session: AsyncSession) -> dict[str, object]:
    start, end = day_bounds(target, user.timezone)
    result = await session.execute(
        select(Entry).where(
            Entry.user_id == user.id, Entry.logged_at >= start, Entry.logged_at <= end
        )
    )
    goals_result = await session.execute(
        select(Goal).where(Goal.user_id == user.id, Goal.effective_from <= target)
    )
    summary = make_daily_summary(target, list(result.scalars()), list(goals_result.scalars()))
    return summary.model_dump(mode="json")


@server.tool()
async def list_entries(
    date: Annotated[
        str | None,
        Field(description="Local date in YYYY-MM-DD format. Use date or from/to, not both."),
    ] = None,
    from_: Annotated[
        str | None,
        Field(
            validation_alias="from",
            description="Start local date in YYYY-MM-DD format, inclusive.",
        ),
    ] = None,
    to_: Annotated[
        str | None,
        Field(
            validation_alias="to",
            description="End local date in YYYY-MM-DD format, inclusive.",
        ),
    ] = None,
) -> str:
    """List the authenticated user's entries with macros in grams.

    Use date for one local day or from_date/to_date for an inclusive local-date range.
    """
    async with SessionLocal() as session:
        user = await _user(session)
        if user is None:
            return "Error: authenticated user was not found."
        try:
            if date is not None and (from_ is not None or to_ is not None):
                return "Error: use date or from/to, not both."
            if date is not None:
                first = last = _parse_date(date, user)
            else:
                first = _parse_date(from_, user)
                last = _parse_date(to_, user) if to_ is not None else first
            if last < first:
                first, last = last, first
            start, _ = day_bounds(first, user.timezone)
            _, end = day_bounds(last, user.timezone)
            result = await session.execute(
                select(Entry)
                .where(
                    Entry.user_id == user.id,
                    Entry.logged_at >= start,
                    Entry.logged_at <= end,
                )
                .order_by(Entry.logged_at)
            )
            return _json([_entry_output(entry) for entry in result.scalars()])
        except (ValueError, TypeError):
            return "Error: dates must use YYYY-MM-DD format."
        except Exception:
            return "Error: could not list entries."


@server.tool()
async def delete_entry(
    entry_id: Annotated[UUID, Field(description="UUID of the entry to delete.")],
) -> str:
    """Delete one entry owned by the authenticated user."""
    async with SessionLocal() as session:
        user = await _user(session)
        if user is None:
            return "Error: authenticated user was not found."
        try:
            result = await session.execute(
                select(Entry).where(Entry.id == entry_id, Entry.user_id == user.id)
            )
            entry = result.scalar_one_or_none()
            if entry is None:
                return "Error: entry was not found."
            await session.delete(entry)
            await session.commit()
            return "Entry deleted successfully."
        except Exception:
            await session.rollback()
            return "Error: could not delete the entry."


@server.tool()
async def search_foods(
    query: Annotated[str, Field(description="Case-insensitive food name or brand search text.")],
    limit: Annotated[int, Field(ge=1, le=200, description="Maximum foods to return.")] = 50,
) -> str:
    """Search visible foods and return nutrition values per 100 g."""
    async with SessionLocal() as session:
        user = await _user(session)
        if user is None:
            return "Error: authenticated user was not found."
        try:
            term = f"%{query}%"
            result = await session.execute(
                select(Food)
                .where(
                    ((Food.user_id == user.id) | Food.user_id.is_(None))
                    & (Food.name.ilike(term) | Food.brand.ilike(term))
                )
                .order_by(Food.name)
                .limit(limit)
            )
            return _json(
                [FoodRead.model_validate(food).model_dump(mode="json") for food in result.scalars()]
            )
        except Exception:
            return "Error: could not search foods."


@server.tool()
async def create_food(
    name: Annotated[str, Field(min_length=1, max_length=200, description="Food name.")],
    kcal: Annotated[float, Field(ge=0, description="Calories per 100 g.")],
    protein_g: Annotated[float, Field(ge=0, description="Protein in grams per 100 g.")],
    carbs_g: Annotated[float, Field(ge=0, description="Carbohydrates in grams per 100 g.")],
    fat_g: Annotated[float, Field(ge=0, description="Fat in grams per 100 g.")],
    brand: Annotated[str | None, Field(description="Optional brand name.")] = None,
    fiber_g: Annotated[float | None, Field(ge=0, description="Fiber in grams per 100 g.")] = None,
    serving_label: Annotated[str | None, Field(description="Optional serving label.")] = None,
    serving_grams: Annotated[
        float | None, Field(ge=0, description="Optional serving size in grams.")
    ] = None,
) -> str:
    """Create a private food for the authenticated user.

    All nutrition values are per 100 g; macro units are grams.
    """
    async with SessionLocal() as session:
        user = await _user(session)
        if user is None:
            return "Error: authenticated user was not found."
        try:
            food = Food(
                user_id=user.id,
                name=name,
                brand=brand,
                kcal=kcal,
                protein_g=protein_g,
                carbs_g=carbs_g,
                fat_g=fat_g,
                fiber_g=fiber_g,
                serving_label=serving_label,
                serving_grams=serving_grams,
            )
            session.add(food)
            await session.commit()
            await session.refresh(food)
            return _json(FoodRead.model_validate(food).model_dump(mode="json"))
        except Exception:
            await session.rollback()
            return "Error: could not create food; name and brand may already exist."


@server.tool()
async def set_daily_goal(
    kcal: Annotated[float, Field(ge=0, description="Daily calorie goal.")],
    protein_g: Annotated[float, Field(ge=0, description="Daily protein goal in grams.")],
    carbs_g: Annotated[float, Field(ge=0, description="Daily carbohydrate goal in grams.")],
    fat_g: Annotated[float, Field(ge=0, description="Daily fat goal in grams.")],
    fiber_g: Annotated[float | None, Field(ge=0, description="Daily fiber goal in grams.")] = None,
    effective_from: Annotated[
        str | None,
        Field(description="Start date in YYYY-MM-DD format; absent means today in user timezone."),
    ] = None,
) -> str:
    """Set or replace a daily macro goal, preserving prior goal history."""
    async with SessionLocal() as session:
        user = await _user(session)
        if user is None:
            return "Error: authenticated user was not found."
        try:
            target = _parse_date(effective_from, user)
            result = await session.execute(
                select(Goal).where(Goal.user_id == user.id, Goal.effective_from == target)
            )
            goal = result.scalar_one_or_none()
            if goal is None:
                goal = Goal(
                    user_id=user.id,
                    effective_from=target,
                    kcal=kcal,
                    protein_g=protein_g,
                    carbs_g=carbs_g,
                    fat_g=fat_g,
                    fiber_g=fiber_g,
                )
                session.add(goal)
            else:
                goal.kcal = Decimal(str(kcal))
                goal.protein_g = Decimal(str(protein_g))
                goal.carbs_g = Decimal(str(carbs_g))
                goal.fat_g = Decimal(str(fat_g))
                goal.fiber_g = Decimal(str(fiber_g)) if fiber_g is not None else None
            await session.commit()
            await session.refresh(goal)
            return _json(GoalRead.model_validate(goal).model_dump(mode="json"))
        except (ValueError, TypeError):
            await session.rollback()
            return "Error: effective_from must use YYYY-MM-DD format."
        except Exception:
            await session.rollback()
            return "Error: could not set the daily goal."


@server.tool()
async def get_daily_progress(
    date: Annotated[
        str | None,
        Field(description="Local date in YYYY-MM-DD format; absent means today."),
    ] = None,
) -> str:
    """Get consumed, goal, remaining, and percentage progress for one local day."""
    async with SessionLocal() as session:
        user = await _user(session)
        if user is None:
            return "Error: authenticated user was not found."
        try:
            target = _parse_date(date, user)
            return _json(await _daily_summary(target, user, session))
        except (ValueError, TypeError):
            return "Error: date must use YYYY-MM-DD format."
        except Exception:
            return "Error: could not calculate daily progress."


@server.tool()
async def get_range_summary(
    from_: Annotated[
        str, Field(validation_alias="from", description="Start date in YYYY-MM-DD format.")
    ],
    to_: Annotated[str, Field(validation_alias="to", description="End date in YYYY-MM-DD format.")],
) -> str:
    """Get each day's progress and period averages for an inclusive local-date range."""
    async with SessionLocal() as session:
        user = await _user(session)
        if user is None:
            return "Error: authenticated user was not found."
        try:
            first = _parse_date(from_, user)
            last = _parse_date(to_, user)
            if last < first:
                first, last = last, first
            start, _ = day_bounds(first, user.timezone)
            _, end = day_bounds(last, user.timezone)
            entries_result = await session.execute(
                select(Entry).where(
                    Entry.user_id == user.id,
                    Entry.logged_at >= start,
                    Entry.logged_at <= end,
                )
            )
            goals_result = await session.execute(
                select(Goal).where(Goal.user_id == user.id, Goal.effective_from <= last)
            )
            goals = list(goals_result.scalars())
            local_zone = ZoneInfo(user.timezone)
            grouped: dict[date, list[Entry]] = {}
            for entry in entries_result.scalars():
                grouped.setdefault(entry.logged_at.astimezone(local_zone).date(), []).append(entry)
            days = [
                make_daily_summary(
                    first + timedelta(days=offset),
                    grouped.get(first + timedelta(days=offset), []),
                    goals,
                )
                for offset in range((last - first).days + 1)
            ]
            count = len(days)
            averages = {
                "kcal": round(sum(day.consumed.kcal for day in days) / count, 2),
                "protein_g": round(sum(day.consumed.protein_g for day in days) / count, 2),
                "carbs_g": round(sum(day.consumed.carbs_g for day in days) / count, 2),
                "fat_g": round(sum(day.consumed.fat_g for day in days) / count, 2),
                "fiber_g": round(sum(day.consumed.fiber_g for day in days) / count, 2),
            }
            return _json(
                {"days": [day.model_dump(mode="json") for day in days], "averages": averages}
            )
        except (ValueError, TypeError):
            return "Error: dates must use YYYY-MM-DD format."
        except Exception:
            return "Error: could not calculate range summary."


def create_mcp_app() -> tuple[ASGIApp, Starlette, DbOAuthProvider]:
    auth_settings = get_auth_settings()
    resource_server_url = auth_settings.resource_server_url
    assert resource_server_url is not None
    transport_app = server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    transport_app.router.redirect_slashes = False
    protected_app = BearerAuthMiddleware(
        MCPPathAdapter(transport_app),
        token_verifier,
        resource_metadata_url=build_resource_metadata_url(resource_server_url),
    )
    return protected_app, transport_app, oauth_provider
