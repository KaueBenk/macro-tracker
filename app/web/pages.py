from __future__ import annotations

import math
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, available_timezones

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.responses import RedirectResponse, Response

from app.db import SessionLocal, get_session
from app.models import Entry, Food, Goal, Meal, User
from app.routers.summary import build_daily_summary, build_range_summary
from app.schemas import DailySummary
from app.services import barcode as barcode_service
from app.services import food_search
from app.services.nutrition import MacroValues, day_bounds, resolve_entry_macros
from app.web.auth import (
    WEB_SESSION_COOKIE,
    csrf_token,
    get_web_user,
    require_csrf,
    templates,
)

router = APIRouter()
MEAL_LABELS = {
    Meal.breakfast: "Café da manhã",
    Meal.lunch: "Almoço",
    Meal.dinner: "Jantar",
    Meal.snack: "Lanche",
    Meal.other: "Outro",
}


def _today(user: User) -> date:
    return datetime.now(ZoneInfo(user.timezone)).date()


def _parse_date(value: str | None, fallback: date) -> tuple[date, str | None]:
    if not value:
        return fallback, None
    try:
        return date.fromisoformat(value), None
    except ValueError:
        return fallback, "Data inválida; exibindo o dia de hoje."


def _parse_number(value: str | None, *, required: bool = False) -> float | None:
    cleaned = (value or "").strip()
    if not cleaned:
        if required:
            raise ValueError("preencha este campo")
        return None
    try:
        number = float(Decimal(cleaned.replace(",", ".")))
    except (InvalidOperation, ValueError):
        raise ValueError("use um número válido") from None
    if not math.isfinite(number) or number < 0:
        raise ValueError("use um número maior ou igual a zero")
    return number


def _parse_local_datetime(value: str | None, user: User) -> datetime:
    if not value:
        return datetime.now(ZoneInfo(user.timezone)).astimezone(UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("data e hora inválidas") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(user.timezone))
    return parsed.astimezone(UTC)


def _csrf(request: Request) -> str:
    raw_token = request.cookies.get(WEB_SESSION_COOKIE)
    if raw_token is None:
        return ""
    return csrf_token(raw_token, request.app.state.settings)


def _base_context(request: Request, user: User, **values: object) -> dict[str, object]:
    return {
        "request": request,
        "user": user,
        "csrf_token": _csrf(request),
        **values,
    }


def _progress(summary: DailySummary) -> list[dict[str, object]]:
    consumed = summary.consumed
    goal = summary.goal
    remaining = summary.remaining
    percent = summary.percent
    values = {
        "kcal": (
            consumed.kcal,
            goal.kcal if goal else None,
            remaining.kcal if remaining else None,
            percent.kcal,
        ),
        "protein_g": (
            consumed.protein_g,
            goal.protein_g if goal else None,
            remaining.protein_g if remaining else None,
            percent.protein_g,
        ),
        "carbs_g": (
            consumed.carbs_g,
            goal.carbs_g if goal else None,
            remaining.carbs_g if remaining else None,
            percent.carbs_g,
        ),
        "fat_g": (
            consumed.fat_g,
            goal.fat_g if goal else None,
            remaining.fat_g if remaining else None,
            percent.fat_g,
        ),
        "fiber_g": (
            consumed.fiber_g,
            goal.fiber_g if goal else None,
            remaining.fiber_g if remaining else None,
            percent.fiber_g,
        ),
    }
    labels = {
        "kcal": ("Calorias", "kcal"),
        "protein_g": ("Proteína", "g"),
        "carbs_g": ("Carboidrato", "g"),
        "fat_g": ("Gordura", "g"),
        "fiber_g": ("Fibra", "g"),
    }
    return [
        {
            "key": key,
            "label": labels[key][0],
            "unit": labels[key][1],
            "consumed": values[key][0],
            "goal": values[key][1],
            "remaining": values[key][2],
            "percent": values[key][3],
            "bar_percent": min(max(values[key][3], 0), 100),
        }
        for key in values
    ]


async def _day_data(
    day: date, user: User, session: AsyncSession
) -> tuple[DailySummary, list[Entry]]:
    summary = await build_daily_summary(day, user, session)
    start, end = day_bounds(day, user.timezone)
    result = await session.execute(
        select(Entry)
        .options(selectinload(Entry.food))
        .where(Entry.user_id == user.id, Entry.logged_at >= start, Entry.logged_at <= end)
        .order_by(Entry.logged_at)
    )
    return summary, list(result.scalars())


@router.get("/app")
async def today_page(
    request: Request,
    web_user: User | RedirectResponse = Depends(get_web_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    if isinstance(web_user, Response):
        return web_user
    day, date_error = _parse_date(request.query_params.get("d"), _today(web_user))
    summary, entries = await _day_data(day, web_user, session)
    return templates.TemplateResponse(
        request=request,
        name="day.html",
        context=_base_context(
            request,
            web_user,
            day=day,
            today_day=_today(web_user).isoformat(),
            previous_day=(day - timedelta(days=1)).isoformat(),
            next_day=(day + timedelta(days=1)).isoformat(),
            user_zone=ZoneInfo(web_user.timezone),
            date_error=date_error,
            summary=summary,
            progress=_progress(summary),
            entries=entries,
            meal_labels=MEAL_LABELS,
        ),
    )


@router.post("/app/entradas/{entry_id}/excluir")
async def delete_entry(
    request: Request,
    entry_id: uuid.UUID,
    user: User = Depends(require_csrf),
) -> Response:
    async with SessionLocal() as session:
        entry = await session.scalar(
            select(Entry).where(Entry.id == entry_id, Entry.user_id == user.id)
        )
        if entry is None:
            raise HTTPException(status_code=404, detail="Entrada não encontrada")
        day = entry.logged_at.astimezone(ZoneInfo(user.timezone)).date()
        await session.delete(entry)
        await session.commit()
        if request.headers.get("hx-request") == "true":
            summary = await build_daily_summary(day, user, session)
            return templates.TemplateResponse(
                request=request,
                name="partials/entry_deleted.html",
                context={"entry_id": entry_id, "progress": _progress(summary)},
            )
    return RedirectResponse(f"/app?d={day.isoformat()}", status_code=303)


def _add_context(
    request: Request,
    user: User,
    *,
    foods: list[Food] | None = None,
    error: str | None = None,
    q: str = "",
    barcode: str = "",
    remote: bool = False,
    form: dict[str, str] | None = None,
) -> dict[str, object]:
    return _base_context(
        request,
        user,
        foods=foods or [],
        error=error,
        q=q,
        barcode=barcode,
        remote=remote,
        form=form or {},
        meal_labels=MEAL_LABELS,
    )


@router.get("/app/adicionar")
async def add_page(
    request: Request,
    q: str = "",
    remote: bool = False,
    barcode: str = "",
    web_user: User | RedirectResponse = Depends(get_web_user),
) -> Response:
    if isinstance(web_user, Response):
        return web_user
    foods: list[Food] = []
    error: str | None = None
    async with SessionLocal() as session:
        if q.strip():
            foods = await food_search.search_foods(
                session, user=web_user, query=q, limit=20, remote=remote
            )
        if barcode.strip():
            try:
                food = await barcode_service.lookup_barcode(session, user=web_user, barcode=barcode)
            except ValueError as exc:
                error = str(exc)
            else:
                if food is not None:
                    foods.insert(0, food)
    context = _add_context(
        request, web_user, foods=foods, error=error, q=q, barcode=barcode, remote=remote
    )
    if request.headers.get("hx-request") == "true":
        return templates.TemplateResponse(
            request=request, name="partials/food_results.html", context=context
        )
    return templates.TemplateResponse(
        request=request,
        name="add.html",
        context=context,
    )


@router.post("/app/entradas")
async def create_entry(
    request: Request,
    user: User = Depends(require_csrf),
) -> Response:
    form_data = await request.form()
    form = {key: str(value) for key, value in form_data.items()}
    try:
        food: Food | None = None
        food_id_value = form.get("food_id", "").strip()
        async with SessionLocal() as session:
            if food_id_value:
                try:
                    food_id = uuid.UUID(food_id_value)
                except ValueError:
                    raise ValueError("alimento inválido") from None
                food = await session.scalar(
                    select(Food).where(
                        Food.id == food_id,
                        (Food.user_id == user.id) | Food.user_id.is_(None),
                    )
                )
                if food is None:
                    raise ValueError("alimento não encontrado")
            quantity = _parse_number(form.get("quantity_g"))
            macros = resolve_entry_macros(
                food,
                quantity,
                MacroValues(
                    _parse_number(form.get("kcal")),
                    _parse_number(form.get("protein_g")),
                    _parse_number(form.get("carbs_g")),
                    _parse_number(form.get("fat_g")),
                    _parse_number(form.get("fiber_g")),
                ),
            )
            try:
                meal = Meal(form.get("meal", Meal.other.value))
            except ValueError:
                raise ValueError("refeição inválida") from None
            logged_at = _parse_local_datetime(form.get("logged_at"), user)
            entry = Entry(
                user_id=user.id,
                logged_at=logged_at,
                meal=meal,
                food_id=food.id if food else None,
                description=form.get("description", "").strip()
                or (food.name if food is not None and food.expires_at else None),
                quantity_g=quantity,
                kcal=Decimal(str(macros.kcal)),
                protein_g=Decimal(str(macros.protein_g)),
                carbs_g=Decimal(str(macros.carbs_g)),
                fat_g=Decimal(str(macros.fat_g)),
                fiber_g=Decimal(str(macros.fiber_g)) if macros.fiber_g is not None else None,
                notes=form.get("notes") or None,
            )
            session.add(entry)
            await session.commit()
        target = logged_at.astimezone(ZoneInfo(user.timezone)).date()
        return RedirectResponse(f"/app?d={target.isoformat()}", status_code=303)
    except (ValueError, TypeError) as exc:
        async with SessionLocal() as session:
            foods = await food_search.search_foods(
                session, user=user, query=form.get("q", ""), limit=20, remote=False
            )
        return templates.TemplateResponse(
            request=request,
            name="add.html",
            status_code=400,
            context=_add_context(request, user, foods=foods, error=str(exc), form=form),
        )


async def _visible_foods(session: AsyncSession, user: User, query: str) -> list[Food]:
    return await food_search.search_foods(session, user=user, query=query, limit=100, remote=False)


@router.get("/app/alimentos")
async def foods_page(
    request: Request,
    q: str = "",
    web_user: User | RedirectResponse = Depends(get_web_user),
) -> Response:
    if isinstance(web_user, Response):
        return web_user
    async with SessionLocal() as session:
        foods = await _visible_foods(session, web_user, q)
    return templates.TemplateResponse(
        request=request,
        name="foods.html",
        context=_base_context(
            request, web_user, foods=foods, q=q, error=None, editing=None, form={}
        ),
    )


def _food_values(form: dict[str, str]) -> dict[str, object]:
    name = form.get("name", "").strip()
    if not name:
        raise ValueError("informe o nome do alimento")
    values: dict[str, object] = {
        "name": name,
        "brand": form.get("brand", "").strip() or None,
        "category": form.get("category", "").strip() or None,
    }
    for field in ("kcal", "protein_g", "carbs_g", "fat_g"):
        values[field] = _parse_number(form.get(field), required=True)
    values["fiber_g"] = _parse_number(form.get("fiber_g"))
    return values


@router.post("/app/alimentos")
async def create_food(
    request: Request,
    user: User = Depends(require_csrf),
) -> Response:
    form_data = await request.form()
    form = {key: str(value) for key, value in form_data.items()}
    try:
        values = _food_values(form)
        async with SessionLocal() as session:
            session.add(Food(user_id=user.id, **values))
            await session.commit()
        return RedirectResponse("/app/alimentos", status_code=303)
    except (ValueError, TypeError) as exc:
        async with SessionLocal() as session:
            foods = await _visible_foods(session, user, "")
        return templates.TemplateResponse(
            request=request,
            name="foods.html",
            status_code=400,
            context=_base_context(
                request, user, foods=foods, q="", error=str(exc), editing=None, form=form
            ),
        )


@router.get("/app/alimentos/{food_id}/editar")
async def edit_food_page(
    request: Request,
    food_id: uuid.UUID,
    web_user: User | RedirectResponse = Depends(get_web_user),
) -> Response:
    if isinstance(web_user, Response):
        return web_user
    async with SessionLocal() as session:
        food = await session.get(Food, food_id)
        if food is None:
            raise HTTPException(status_code=404, detail="Alimento não encontrado")
        if food.user_id is None:
            raise HTTPException(status_code=403, detail="Alimentos globais são somente leitura")
        if food.user_id != web_user.id:
            raise HTTPException(status_code=404, detail="Alimento não encontrado")
        foods = await _visible_foods(session, web_user, "")
    return templates.TemplateResponse(
        request=request,
        name="foods.html",
        context=_base_context(
            request, web_user, foods=foods, q="", error=None, editing=food, form={}
        ),
    )


@router.post("/app/alimentos/{food_id}/editar")
async def update_food(
    request: Request,
    food_id: uuid.UUID,
    user: User = Depends(require_csrf),
) -> Response:
    form_data = await request.form()
    form = {key: str(value) for key, value in form_data.items()}
    async with SessionLocal() as session:
        food = await session.get(Food, food_id)
        if food is None:
            raise HTTPException(status_code=404, detail="Alimento não encontrado")
        if food.user_id is None:
            raise HTTPException(status_code=403, detail="Alimentos globais são somente leitura")
        if food.user_id != user.id:
            raise HTTPException(status_code=404, detail="Alimento não encontrado")
        try:
            values = _food_values(form)
            for key, value in values.items():
                setattr(food, key, value)
            await session.commit()
        except (ValueError, TypeError) as exc:
            foods = await _visible_foods(session, user, "")
            return templates.TemplateResponse(
                request=request,
                name="foods.html",
                status_code=400,
                context=_base_context(
                    request, user, foods=foods, q="", error=str(exc), editing=food, form=form
                ),
            )
    return RedirectResponse("/app/alimentos", status_code=303)


@router.post("/app/alimentos/{food_id}/excluir")
async def delete_food(
    request: Request,
    food_id: uuid.UUID,
    user: User = Depends(require_csrf),
) -> Response:
    async with SessionLocal() as session:
        food = await session.get(Food, food_id)
        if food is None:
            raise HTTPException(status_code=404, detail="Alimento não encontrado")
        if food.user_id is None:
            raise HTTPException(status_code=403, detail="Alimentos globais são somente leitura")
        if food.user_id != user.id:
            raise HTTPException(status_code=404, detail="Alimento não encontrado")
        await session.delete(food)
        await session.commit()
    if request.headers.get("hx-request") == "true":
        return Response("")
    return RedirectResponse("/app/alimentos", status_code=303)


@router.get("/app/metas")
async def goals_page(
    request: Request,
    web_user: User | RedirectResponse = Depends(get_web_user),
) -> Response:
    if isinstance(web_user, Response):
        return web_user
    async with SessionLocal() as session:
        goals = list(
            (
                await session.execute(
                    select(Goal)
                    .where(Goal.user_id == web_user.id)
                    .order_by(Goal.effective_from.desc())
                )
            ).scalars()
        )
    return templates.TemplateResponse(
        request=request,
        name="goals.html",
        context=_base_context(request, web_user, goals=goals, error=None, form={}),
    )


@router.post("/app/metas")
async def create_goal(
    request: Request,
    user: User = Depends(require_csrf),
) -> Response:
    form_data = await request.form()
    form = {key: str(value) for key, value in form_data.items()}
    try:
        effective_from = date.fromisoformat(form.get("effective_from") or _today(user).isoformat())
        values = {
            field: _parse_number(form.get(field), required=True)
            for field in ("kcal", "protein_g", "carbs_g", "fat_g")
        }
        values["fiber_g"] = _parse_number(form.get("fiber_g"))
        async with SessionLocal() as session:
            goal = await session.scalar(
                select(Goal).where(
                    Goal.user_id == user.id,
                    Goal.effective_from == effective_from,
                )
            )
            if goal is None:
                session.add(Goal(user_id=user.id, effective_from=effective_from, **values))
            else:
                for key, value in values.items():
                    setattr(goal, key, value)
            await session.commit()
        return RedirectResponse("/app/metas", status_code=303)
    except (ValueError, TypeError) as exc:
        async with SessionLocal() as session:
            goals = list(
                (
                    await session.execute(
                        select(Goal)
                        .where(Goal.user_id == user.id)
                        .order_by(Goal.effective_from.desc())
                    )
                ).scalars()
            )
        return templates.TemplateResponse(
            request=request,
            name="goals.html",
            status_code=400,
            context=_base_context(request, user, goals=goals, error=str(exc), form=form),
        )


@router.get("/app/historico")
async def history_page(
    request: Request,
    dias: str = "7",
    web_user: User | RedirectResponse = Depends(get_web_user),
) -> Response:
    if isinstance(web_user, Response):
        return web_user
    days_count = 30 if dias == "30" else 7
    end = _today(web_user)
    start = end - timedelta(days=days_count - 1)
    async with SessionLocal() as session:
        summary = await build_range_summary(start, end, web_user, session)
    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context=_base_context(
            request,
            web_user,
            summary=summary,
            days_count=days_count,
            invalid_days=dias not in {"7", "30"},
        ),
    )


TIMEZONES = sorted(available_timezones())


@router.get("/app/conta")
async def account_page(
    request: Request,
    web_user: User | RedirectResponse = Depends(get_web_user),
) -> Response:
    if isinstance(web_user, Response):
        return web_user
    return templates.TemplateResponse(
        request=request,
        name="account.html",
        context=_base_context(request, web_user, timezones=TIMEZONES, error=None),
    )


@router.post("/app/conta")
async def update_account(
    request: Request,
    user: User = Depends(require_csrf),
) -> Response:
    form = await request.form()
    timezone_name = str(form.get("timezone") or "")
    try:
        ZoneInfo(timezone_name)
    except (KeyError, ValueError):
        return templates.TemplateResponse(
            request=request,
            name="account.html",
            status_code=400,
            context=_base_context(
                request,
                user,
                timezones=TIMEZONES,
                error="Escolha um fuso horário válido.",
            ),
        )
    async with SessionLocal() as session:
        stored_user = await session.get(User, user.id)
        if stored_user is None:
            raise HTTPException(status_code=403, detail="Sessão inválida")
        stored_user.timezone = timezone_name
        await session.commit()
    return RedirectResponse("/app/conta", status_code=303)
