import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import Settings
from app.db import SessionLocal
from app.models import Food
from app.providers.base import ProviderFood
from app.services import barcode as barcode_service
from app.services.barcode import lookup_barcode
from tests.conftest import create_identity


class FakeBarcodeProvider:
    source = "off"

    def __init__(self, food: ProviderFood | None = None, *, delay: float = 0) -> None:
        self.food = food
        self.delay = delay
        self.calls = 0

    async def fetch_barcode(self, barcode: str) -> ProviderFood | None:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.food


def _provider_food() -> ProviderFood:
    return ProviderFood(
        source="off",
        source_ref="7891234567890",
        barcode="7891234567890",
        name="Biscoito remoto",
        kcal=400,
        protein_g=5,
        carbs_g=60,
        fat_g=15,
        attribution="Open Food Facts contributors, openfoodfacts.org (ODbL)",
    )


@pytest.mark.asyncio
async def test_lookup_barcode_local_first_does_not_call_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _ = await create_identity("barcode-local@example.com")
    async with SessionLocal() as session:
        food = Food(
            user_id=user.id,
            name="Minha barra",
            barcode="000123",
            kcal=100,
            protein_g=1,
            carbs_g=10,
            fat_g=2,
        )
        session.add(food)
        await session.commit()
    provider = FakeBarcodeProvider(_provider_food())
    monkeypatch.setattr(barcode_service, "get_enabled_providers", lambda: {"off": provider})
    async with SessionLocal() as session:
        result = await lookup_barcode(session, user=user, barcode="abc-000123")
    assert result is not None and result.name == "Minha barra"
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_lookup_barcode_materializes_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _ = await create_identity("barcode-remote@example.com")
    provider = FakeBarcodeProvider(_provider_food())
    monkeypatch.setattr(barcode_service, "get_enabled_providers", lambda: {"off": provider})
    async with SessionLocal() as session:
        first = await lookup_barcode(session, user=user, barcode="7891234567890")
        second = await lookup_barcode(session, user=user, barcode="7891234567890")
        count = await session.scalar(
            select(Food).where(Food.source == "off", Food.barcode == "7891234567890")
        )
    assert first is not None and first.attribution is not None
    assert second is not None and second.id == first.id
    assert count is not None
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_lookup_barcode_timeout_is_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _ = await create_identity("barcode-timeout@example.com")
    provider = FakeBarcodeProvider(_provider_food(), delay=3.2)
    monkeypatch.setattr(barcode_service, "get_enabled_providers", lambda: {"off": provider})
    monkeypatch.setattr(
        barcode_service,
        "get_settings",
        lambda: Settings(provider_timeout_seconds=0.01),
    )
    async with SessionLocal() as session:
        result = await lookup_barcode(session, user=user, barcode="7891234567890")
    assert result is None


@pytest.mark.asyncio
async def test_barcode_route_does_not_collide_with_food_uuid(
    client: AsyncClient,
) -> None:
    user, token = await create_identity("barcode-route@example.com")
    async with SessionLocal() as session:
        session.add(
            Food(
                user_id=user.id,
                name="Route food",
                barcode="012345",
                kcal=100,
                protein_g=1,
                carbs_g=2,
                fat_g=3,
            )
        )
        await session.commit()
    response = await client.get(
        "/api/foods/barcode/012345",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Route food"
