import asyncio
import json

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.config import Settings
from app.db import SessionLocal
from app.main import create_app
from app.models import Food
from app.providers.base import ProviderError, ProviderFood
from app.providers.registry import get_enabled_providers, register_provider
from app.providers.usda import USDAProvider
from app.services import food_search as food_search_service
from app.services.food_cache import upsert_provider_foods
from tests.conftest import create_identity


def _nutrient(number: str, value: float) -> dict[str, object]:
    return {"nutrientNumber": number, "value": value}


def _food_payload(
    nutrients: list[dict[str, object]],
    *,
    food_id: int = 123,
    data_type: str = "Branded",
) -> dict[str, object]:
    return {
        "fdcId": food_id,
        "description": "Canned beans",
        "brandName": "Example",
        "gtinUpc": "012345678905",
        "foodCategory": "Legumes",
        "dataType": data_type,
        "foodNutrients": nutrients,
    }


@pytest.mark.asyncio
async def test_usda_search_parses_per_100_g_nutrients() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/fdc/v1/foods/search"
        assert request.url.params["api_key"] == "test-key"
        body = json.loads(request.content)
        assert body == {
            "query": "beans",
            "pageSize": 5,
            "dataType": ["Foundation", "SR Legacy", "Branded"],
        }
        return httpx.Response(200, json={"foods": [_food_payload([_nutrient("208", 120)])]})

    provider = USDAProvider(
        Settings(usda_api_key="test-key"),
        transport=httpx.MockTransport(handler),
    )
    foods = await provider.search("beans", 5)
    assert foods[0].source == "usda"
    assert foods[0].source_ref == "123"
    assert foods[0].kcal == 120
    assert foods[0].protein_g == 0
    assert foods[0].fiber_g is None
    assert foods[0].barcode == "012345678905"
    assert foods[0].brand == "Example"
    assert foods[0].source_version == "Branded"
    assert foods[0].locale == "en-US"


@pytest.mark.asyncio
async def test_usda_fetch_parses_nested_nutrient_numbers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/fdc/v1/food/456"
        return httpx.Response(
            200,
            json={
                **_food_payload([], food_id=456, data_type="Foundation"),
                "foodNutrients": [
                    {"nutrient": {"number": "208"}, "amount": 99},
                    {"nutrient": {"number": "203"}, "amount": 8},
                    {"nutrient": {"number": "204"}, "amount": 1},
                    {"nutrient": {"number": "205"}, "amount": 12},
                    {"nutrient": {"number": "291"}, "amount": 4},
                ],
            },
        )

    provider = USDAProvider(
        Settings(usda_api_key="test-key"),
        transport=httpx.MockTransport(handler),
    )
    food = await provider.fetch("456")
    assert food is not None
    assert food.source_ref == "456"
    assert food.kcal == 99
    assert food.protein_g == 8
    assert food.carbs_g == 12
    assert food.fat_g == 1
    assert food.fiber_g == 4


@pytest.mark.parametrize(
    ("nutrients", "expected_kcal"),
    [
        ([_nutrient("957", 70)], 70),
        ([_nutrient("958", 71)], 71),
        ([_nutrient("268", 418.4)], 100),
    ],
)
def test_usda_energy_fallbacks(nutrients: list[dict[str, object]], expected_kcal: float) -> None:
    food = USDAProvider._parse_food(_food_payload(nutrients))
    assert food is not None
    assert food.kcal == pytest.approx(expected_kcal)


def test_usda_food_without_energy_is_discarded() -> None:
    assert USDAProvider._parse_food(_food_payload([_nutrient("203", 4)])) is None


def test_usda_factory_requires_api_key() -> None:
    assert get_enabled_providers(Settings(food_provider_sources="usda")) == {}


def test_provider_registry_accepts_factories() -> None:
    fake = FakeProvider([_fake_food()])
    register_provider("fake", lambda _: fake)
    assert get_enabled_providers(Settings(food_provider_sources="fake")) == {"fake": fake}


@pytest.mark.asyncio
async def test_usda_rate_limit_is_provider_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"message": "hourly limit exceeded"})

    provider = USDAProvider(
        Settings(usda_api_key="test-key"),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError, match="hourly limit exceeded"):
        await provider.search("beans", 5)


@pytest.mark.asyncio
async def test_usda_malformed_payload_and_network_error_are_provider_errors() -> None:
    malformed = USDAProvider(
        Settings(usda_api_key="test-key"),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"foods": "bad"})),
    )
    with pytest.raises(ProviderError, match="foods list"):
        await malformed.search("beans", 5)

    def network_failure(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed")

    unavailable = USDAProvider(
        Settings(usda_api_key="test-key"),
        transport=httpx.MockTransport(network_failure),
    )
    with pytest.raises(ProviderError, match="connection failed"):
        await unavailable.search("beans", 5)


@pytest.mark.asyncio
async def test_provider_food_cache_is_idempotent_and_preserves_user_food() -> None:
    user, _ = await create_identity("cache@example.com")
    user_food = Food(
        user_id=user.id,
        source="usda",
        source_ref="collision",
        name="My private food",
        kcal=10,
        protein_g=1,
        carbs_g=1,
        fat_g=1,
    )
    async with SessionLocal() as session:
        session.add(user_food)
        await session.commit()
    provider_foods = [
        ProviderFood(
            source="usda",
            source_ref="collision",
            name="Remote collision",
            kcal=100,
            protein_g=10,
            carbs_g=20,
            fat_g=2,
            attribution="USDA",
        ),
        ProviderFood(
            source="usda",
            source_ref="1",
            name="Remote beans",
            kcal=80,
            protein_g=5,
            carbs_g=10,
            fat_g=1,
            attribution="USDA",
        ),
    ]
    async with SessionLocal() as session:
        await upsert_provider_foods(session, provider_foods)
    provider_foods[1].kcal = 90
    async with SessionLocal() as session:
        await upsert_provider_foods(session, provider_foods)
        remote_count = await session.scalar(
            select(func.count(Food.id)).where(Food.source == "usda", Food.source_ref == "1")
        )
        remote = await session.scalar(
            select(Food).where(Food.source == "usda", Food.source_ref == "1")
        )
        collision = await session.scalar(select(Food).where(Food.id == user_food.id))
    assert remote_count == 1
    assert remote is not None and remote.kcal == 90
    assert remote.expires_at is None
    assert collision is not None and collision.name == "My private food"


class FakeProvider:
    source = "usda"

    def __init__(
        self,
        result: list[ProviderFood] | None = None,
        *,
        delay: float = 0,
    ) -> None:
        self.result = result or []
        self.delay = delay
        self.calls = 0

    async def search(self, query: str, limit: int) -> list[ProviderFood]:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.result[:limit]

    async def fetch(self, source_ref: str) -> ProviderFood | None:
        return None


def _fake_food() -> ProviderFood:
    return ProviderFood(
        source="usda",
        source_ref="remote-1",
        name="Remote lentils",
        kcal=110,
        protein_g=8,
        carbs_g=18,
        fat_g=1,
        attribution="USDA",
    )


@pytest.mark.asyncio
async def test_remote_false_does_not_call_provider(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, token = await create_identity("no-remote@example.com")
    provider = FakeProvider([_fake_food()])
    monkeypatch.setattr(food_search_service, "get_enabled_providers", lambda: {"usda": provider})
    response = await client.get(
        "/api/foods",
        params={"search": "lentils"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json() == []
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_slow_remote_provider_is_ignored(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, token = await create_identity("slow-provider@example.com")
    provider = FakeProvider(delay=3.2)
    monkeypatch.setattr(food_search_service, "get_enabled_providers", lambda: {"usda": provider})
    response = await client.get(
        "/api/foods",
        params={"search": "lentils", "remote": "true"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_remote_rest_and_mcp_search_have_parity(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, token = await create_identity("remote-parity@example.com")
    provider = FakeProvider([_fake_food()])
    monkeypatch.setattr(food_search_service, "get_enabled_providers", lambda: {"usda": provider})
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    rest = await client.get(
        "/api/foods",
        params={"search": "lentils", "remote": "true"},
        headers=headers,
    )
    assert rest.status_code == 200

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
                        "arguments": {"query": "lentils", "remote": True},
                    },
                },
            )
    assert mcp.status_code == 200
    mcp_foods = json.loads(mcp.json()["result"]["content"][0]["text"])
    assert len(mcp_foods) == len(rest.json())
    for rest_food, mcp_food in zip(rest.json(), mcp_foods):
        assert {key: value for key, value in rest_food.items() if key != "updated_at"} == {
            key: value for key, value in mcp_food.items() if key != "updated_at"
        }
