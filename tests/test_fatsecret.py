from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import Settings
from app.db import SessionLocal
from app.models import Entry, Food, Meal
from app.providers.base import ProviderError, ProviderFood
from app.providers.fatsecret import (
    _TOKEN_CACHE,
    FATSECRET_ATTRIBUTION,
    FatSecretProvider,
    fatsecret_factory,
)
from app.services import barcode as barcode_service
from app.services import food_search as food_search_service
from app.services.food_search import search_foods
from tests.conftest import create_identity


def _settings() -> Settings:
    return Settings(fatsecret_client_id="client", fatsecret_client_secret="secret")


@pytest.fixture(autouse=True)
def clear_fatsecret_token_cache() -> Generator[None, None, None]:
    _TOKEN_CACHE.clear()
    yield
    _TOKEN_CACHE.clear()


def _detail(
    *,
    servings: Any,
    calories: str | None = "90",
    food_id: str = "42",
) -> dict[str, Any]:
    food: dict[str, Any] = {
        "food_id": food_id,
        "food_name": "Synthetic FatSecret food",
        "food_type": "Brand",
        "servings": servings,
    }
    if calories is not None:
        food["servings"] = {
            "serving": [{**serving, "calories": calories} for serving in servings["serving"]]
        }
    return {"food": food}


def _serving(amount: str, unit: str = "g") -> dict[str, str]:
    return {
        "metric_serving_amount": amount,
        "metric_serving_unit": unit,
        "calories": "90",
        "protein": "3",
        "carbohydrate": "12",
        "fat": "2",
        "fiber": "1",
    }


@pytest.mark.asyncio
async def test_fatsecret_search_gets_token_once_and_scales_serving() -> None:
    token_calls = 0
    api_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls, api_calls
        if request.url.host == "oauth.fatsecret.com":
            token_calls += 1
            assert request.headers["Authorization"].startswith("Basic ")
            assert parse_qs(request.content.decode()) == {
                "grant_type": ["client_credentials"],
                "scope": ["basic"],
            }
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        api_calls += 1
        assert request.headers["Authorization"] == "Bearer token"
        if request.url.params["method"] == "foods.search":
            return httpx.Response(
                200,
                json={"foods": {"food": [{"food_id": "42", "food_name": "Synthetic"}]}},
            )
        return httpx.Response(
            200,
            json=_detail(servings={"serving": [_serving("30")]}),
        )

    provider = FatSecretProvider(_settings(), transport=httpx.MockTransport(handler))
    foods = await provider.search("synthetic", 5)
    assert foods[0].kcal == pytest.approx(300)
    assert foods[0].protein_g == pytest.approx(10)
    assert foods[0].carbs_g == pytest.approx(40)
    assert foods[0].fat_g == pytest.approx(6.6666667)
    assert foods[0].fiber_g == pytest.approx(3.3333333)
    await provider.fetch("42")
    assert token_calls == 1
    assert api_calls == 3


@pytest.mark.asyncio
async def test_fatsecret_detail_limit_and_error_payload() -> None:
    detail_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal detail_calls
        if request.url.host == "oauth.fatsecret.com":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        if request.url.params["method"] == "foods.search":
            return httpx.Response(
                200,
                json={
                    "foods": {
                        "food": [
                            {"food_id": "1", "food_name": "One"},
                            {"food_id": "2", "food_name": "Two"},
                        ]
                    }
                },
            )
        detail_calls += 1
        return httpx.Response(200, json=_detail(servings={"serving": [_serving("100")]}))

    provider = FatSecretProvider(
        Settings(
            fatsecret_client_id="client",
            fatsecret_client_secret="secret",
            fatsecret_detail_limit=1,
        ),
        transport=httpx.MockTransport(handler),
    )
    assert len(await provider.search("food", 5)) == 1
    assert detail_calls == 1

    def api_error(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth.fatsecret.com":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        return httpx.Response(200, json={"error": {"message": "invalid food"}})

    failing = FatSecretProvider(_settings(), transport=httpx.MockTransport(api_error))
    with pytest.raises(ProviderError, match="invalid food"):
        await failing.fetch("missing")


@pytest.mark.asyncio
async def test_fatsecret_expired_token_is_renewed() -> None:
    token_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if request.url.host == "oauth.fatsecret.com":
            token_calls += 1
            return httpx.Response(200, json={"access_token": str(token_calls), "expires_in": 3600})
        return httpx.Response(200, json=_detail(servings={"serving": [_serving("100")]}))

    provider = FatSecretProvider(_settings(), transport=httpx.MockTransport(handler))
    await provider.fetch("42")
    _TOKEN_CACHE["client"].expires_at = 0
    await provider.fetch("42")
    assert token_calls == 2


@pytest.mark.asyncio
async def test_distinct_fatsecret_providers_share_token_cache() -> None:
    token_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if request.url.host == "oauth.fatsecret.com":
            token_calls += 1
            return httpx.Response(200, json={"access_token": "shared", "expires_in": 3600})
        return httpx.Response(200, json=_detail(servings={"serving": [_serving("100")]}))

    transport = httpx.MockTransport(handler)
    first = FatSecretProvider(_settings(), transport=transport)
    second = FatSecretProvider(_settings(), transport=transport)
    await first.fetch("42")
    await second.fetch("42")
    assert token_calls == 1


def test_fatsecret_serving_selection_and_discard_rules() -> None:
    food = FatSecretProvider._parse_food(
        {
            "food_id": "42",
            "food_name": "Synthetic",
            "servings": {
                "serving": [
                    _serving("30"),
                    {**_serving("100"), "calories": "250"},
                ]
            },
        }
    )
    assert food is not None and food.kcal == 250
    assert (
        FatSecretProvider._parse_food(
            {
                "food_id": "43",
                "food_name": "Liquid",
                "servings": {"serving": [_serving("250", "ml")]},
            }
        )
        is None
    )
    assert (
        FatSecretProvider._parse_food(
            {
                "food_id": "44",
                "food_name": "No calories",
                "servings": {"serving": [{**_serving("100"), "calories": None}]},
            }
        )
        is None
    )
    singleton = FatSecretProvider._parse_food(
        {"food_id": "45", "food_name": "Singleton", "servings": {"serving": _serving("100")}}
    )
    assert singleton is not None


@pytest.mark.asyncio
async def test_fatsecret_errors_and_factory() -> None:
    no_credentials = Settings()
    assert fatsecret_factory(no_credentials) is None

    def token_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    provider = FatSecretProvider(_settings(), transport=httpx.MockTransport(token_error))
    with pytest.raises(ProviderError, match="rate limited"):
        await provider.fetch("42")


@pytest.mark.asyncio
async def test_fatsecret_materialization_uses_24_hour_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _ = await create_identity("fatsecret-cache@example.com")

    class FakeProvider:
        source = "fatsecret"

        async def search(self, query: str, limit: int) -> list[ProviderFood]:
            return [
                ProviderFood(
                    source="fatsecret",
                    source_ref="42",
                    name="Synthetic cached food",
                    kcal=100,
                    protein_g=1,
                    carbs_g=2,
                    fat_g=3,
                    attribution=FATSECRET_ATTRIBUTION,
                )
            ]

        async def fetch(self, source_ref: str) -> ProviderFood | None:
            return None

    monkeypatch.setattr(
        food_search_service, "get_enabled_providers", lambda: {"fatsecret": FakeProvider()}
    )
    async with SessionLocal() as session:
        await search_foods(session, user=user, query="cached", limit=5, remote=True)
        food = await session.scalar(select(Food).where(Food.source == "fatsecret"))
        assert food is not None
        assert food.expires_at is not None
        remaining = food.expires_at - datetime.now(UTC)
        assert timedelta(hours=23, minutes=59) < remaining <= timedelta(hours=24)


@pytest.mark.asyncio
async def test_expired_food_is_excluded_from_search_and_barcode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _ = await create_identity("fatsecret-expired@example.com")
    async with SessionLocal() as session:
        session.add(
            Food(
                source="fatsecret",
                source_ref="42",
                barcode="123",
                name="Expired food",
                kcal=100,
                protein_g=1,
                carbs_g=2,
                fat_g=3,
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
        await session.commit()
        assert await search_foods(session, user=user, query="expired", limit=5) == []
    monkeypatch.setattr(barcode_service, "get_enabled_providers", lambda: {})
    async with SessionLocal() as session:
        assert await barcode_service.lookup_barcode(session, user=user, barcode="123") is None


@pytest.mark.asyncio
async def test_purge_expired_foods_preserves_entry_snapshot_and_other_foods() -> None:
    from scripts.purge_expired_foods import purge_expired_foods

    user, _ = await create_identity("fatsecret-purge@example.com")
    async with SessionLocal() as session:
        expired = Food(
            source="fatsecret",
            source_ref="expired",
            name="Expired food",
            kcal=100,
            protein_g=1,
            carbs_g=2,
            fat_g=3,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        permanent = Food(
            source="usda",
            source_ref="permanent",
            name="Permanent food",
            kcal=100,
            protein_g=1,
            carbs_g=2,
            fat_g=3,
        )
        private = Food(
            user_id=user.id,
            name="Private food",
            kcal=100,
            protein_g=1,
            carbs_g=2,
            fat_g=3,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        session.add_all([expired, permanent, private])
        await session.flush()
        entry = Entry(
            user_id=user.id,
            food_id=expired.id,
            logged_at=datetime.now(UTC),
            meal=Meal.snack,
            kcal=100,
            protein_g=1,
            carbs_g=2,
            fat_g=3,
            description="Snapshot",
        )
        session.add(entry)
        await session.commit()
        entry_id = entry.id
    assert await purge_expired_foods() == 1
    async with SessionLocal() as session:
        saved = await session.get(Entry, entry_id)
        assert saved is not None
        assert saved.food_id is None
        assert float(saved.kcal) == 100
        assert await session.scalar(select(Food).where(Food.source == "usda")) is not None
        assert await session.scalar(select(Food).where(Food.user_id == user.id)) is not None
    assert await purge_expired_foods() == 0


@pytest.mark.asyncio
async def test_entry_description_defaults_to_expirable_food_name(
    client: AsyncClient,
) -> None:
    user, token = await create_identity("fatsecret-entry@example.com")
    async with SessionLocal() as session:
        food = Food(
            source="fatsecret",
            source_ref="42",
            name="Expirable synthetic food",
            kcal=100,
            protein_g=1,
            carbs_g=2,
            fat_g=3,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        session.add(food)
        await session.commit()
        food_id = food.id
    response = await client.post(
        "/api/entries",
        headers={"Authorization": f"Bearer {token}"},
        json={"food_id": str(food_id), "quantity_g": 100, "meal": "snack"},
    )
    assert response.status_code == 201
    assert response.json()["description"] == "Expirable synthetic food"
