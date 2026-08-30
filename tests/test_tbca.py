import asyncio
from urllib.parse import parse_qs

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import Settings
from app.db import SessionLocal
from app.models import Food
from app.providers.base import ProviderError, ProviderFood
from app.providers.tbca import TBCA_ATTRIBUTION, TBCAProvider
from app.services import food_search as food_search_service
from app.services.food_search import search_foods
from tests.conftest import create_identity

LISTING_HREF = (
    "int_composicao_alimentos.php?n0REd3kv7e86D%2BViXWYUnQ%3D%3D=QagWPGGLCefQ%2BGqdjKbs2w%3D%3D"
)

LISTING_HTML = f"""
<table id="resultados">
  <tr><th>Código</th><th>Descrição</th><th>Porção</th><th>Grupo</th></tr>
  <tr>
    <td><a href="{LISTING_HREF}">BRC0001C</a></td>
    <td>Alimento <i>de teste</i></td><td>-</td><td>C - Frutas e derivados</td>
  </tr>
  <tr>
    <td><a href="int_composicao_alimentos.php?opaque=second%2Bvalue">BRC0002C</a></td>
    <td>Outro alimento</td><td>-</td><td>G - Inventado</td>
  </tr>
  <tr>
    <td><a href="int_composicao_alimentos.php?opaque=third">BRC0003C</a></td>
    <td>Terceiro alimento</td><td>-</td><td>G - Inventado</td>
  </tr>
</table>
"""

DETAIL_HTML = """
<html><body>
<table id="tabela1">
  <tr><th>Componente</th><th>Unidades</th><th>Valor por 100g</th><th>Medida</th></tr>
  <tr><td>Energia</td><td>kcal</td><td>123,45</td><td>porção</td></tr>
  <tr><td>Proteína</td><td>g</td><td>5,84</td><td>porção</td></tr>
  <tr><td>Lipídios</td><td>g</td><td>2,10</td><td>porção</td></tr>
  <tr><td>Carboidrato disponível</td><td>g</td><td>99,00</td><td>porção</td></tr>
  <tr><td>Carboidrato total</td><td>g</td><td>20,50</td><td>porção</td></tr>
  <tr><td>Fibra alimentar</td><td>g</td><td>tr</td><td>porção</td></tr>
</table>
</body></html>
"""


def _transport(handler: object) -> httpx.MockTransport:
    return httpx.MockTransport(handler)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_tbca_search_parses_opaque_links_and_detail_values() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["User-Agent"] == Settings().off_user_agent
        if request.method == "POST":
            assert parse_qs(request.content.decode()) == {
                "guarda": ["tomo1"],
                "produto": ["fruta"],
            }
            return httpx.Response(200, text=LISTING_HTML)
        assert request.url.query.decode() == LISTING_HREF.split("?", 1)[1]
        return httpx.Response(200, text=DETAIL_HTML)

    provider = TBCAProvider(Settings(tbca_detail_limit=1), transport=_transport(handler))
    foods = await provider.search("fruta", 5)
    assert len(foods) == 1
    assert foods[0].source_ref == "BRC0001C"
    assert foods[0].name == "Alimento de teste"
    assert foods[0].category == "Frutas e derivados"
    assert foods[0].kcal == pytest.approx(123.45)
    assert foods[0].protein_g == pytest.approx(5.84)
    assert foods[0].carbs_g == pytest.approx(20.5)
    assert foods[0].fat_g == pytest.approx(2.1)
    assert foods[0].fiber_g == 0
    assert foods[0].attribution == TBCA_ATTRIBUTION
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_tbca_detail_requests_are_limited_to_three_concurrent() -> None:
    active = 0
    maximum = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, maximum
        if request.method == "POST":
            return httpx.Response(200, text=LISTING_HTML)
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(200, text=DETAIL_HTML)

    provider = TBCAProvider(Settings(tbca_detail_limit=5), transport=_transport(handler))
    await provider.search("alimento", 5)
    assert maximum == 3


@pytest.mark.asyncio
async def test_tbca_detail_limit_and_kj_fallback() -> None:
    detail_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal detail_requests
        if request.method == "POST":
            return httpx.Response(200, text=LISTING_HTML)
        detail_requests += 1
        return httpx.Response(
            200,
            text=DETAIL_HTML.replace("123,45", "418,4").replace("kcal", "kJ", 1),
        )

    provider = TBCAProvider(Settings(tbca_detail_limit=2), transport=_transport(handler))
    foods = await provider.search("alimento", 5)
    assert detail_requests == 2
    assert len(foods) == 2
    assert foods[0].kcal == pytest.approx(100)


@pytest.mark.asyncio
async def test_tbca_missing_energy_is_discarded_and_na_is_absent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, text=LISTING_HTML)
        return httpx.Response(
            200,
            text=DETAIL_HTML.replace(
                "<td>Energia</td><td>kcal</td><td>123,45</td>",
                "<td>Energia</td><td>kcal</td><td>NA</td>",
            ).replace(
                "<td>Proteína</td><td>g</td><td>5,84</td>", "<td>Proteína</td><td>g</td><td>NA</td>"
            ),
        )

    provider = TBCAProvider(Settings(tbca_detail_limit=1), transport=_transport(handler))
    assert await provider.search("alimento", 1) == []


@pytest.mark.asyncio
async def test_tbca_http_error_is_provider_error() -> None:
    provider = TBCAProvider(
        Settings(),
        transport=_transport(lambda _: httpx.Response(429, text="too many requests")),
    )
    with pytest.raises(ProviderError, match="429"):
        await provider.search("alimento", 1)


class SlowTBCAProvider:
    source = "tbca"

    async def search(self, query: str, limit: int) -> list[ProviderFood]:
        await asyncio.sleep(0.05)
        return []

    async def fetch(self, source_ref: str) -> ProviderFood | None:
        return None


@pytest.mark.asyncio
async def test_tbca_timeout_is_ignored_by_remote_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _ = await create_identity("tbca-timeout@example.com")
    monkeypatch.setattr(
        food_search_service, "get_enabled_providers", lambda: {"tbca": SlowTBCAProvider()}
    )
    monkeypatch.setattr(
        food_search_service,
        "get_settings",
        lambda: Settings(provider_timeout_seconds=0.001),
    )
    async with SessionLocal() as session:
        assert await search_foods(session, user=user, query="teste", limit=5, remote=True) == []


@pytest.mark.asyncio
async def test_tbca_remote_search_materializes_and_reuses_cache(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, token = await create_identity("tbca-remote@example.com")
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if request.method == "POST":
            return httpx.Response(200, text=LISTING_HTML)
        return httpx.Response(200, text=DETAIL_HTML)

    provider = TBCAProvider(Settings(tbca_detail_limit=1), transport=_transport(handler))
    monkeypatch.setattr(food_search_service, "get_enabled_providers", lambda: {"tbca": provider})
    first = await client.get(
        "/api/foods",
        params={"search": "alimento", "remote": "true"},
        headers={"Authorization": f"Bearer {token}"},
    )
    second = await client.get(
        "/api/foods",
        params={"search": "alimento", "remote": "true"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()[0]["source"] == "tbca"
    assert first.json()[0]["attribution"] == TBCA_ATTRIBUTION
    assert requests == 4
    async with SessionLocal() as session:
        assert (
            await session.scalar(
                select(Food).where(Food.source == "tbca", Food.source_ref == "BRC0001C")
            )
            is not None
        )


@pytest.mark.asyncio
async def test_tbca_ranks_after_taco_and_before_usda() -> None:
    user, _ = await create_identity("tbca-ranking@example.com")
    async with SessionLocal() as session:
        session.add_all(
            [
                Food(
                    name="Arroz",
                    source=source,
                    source_ref=source,
                    kcal=1,
                    protein_g=1,
                    carbs_g=1,
                    fat_g=1,
                )
                for source in ("usda", "tbca", "taco")
            ]
        )
        await session.commit()
        foods = await search_foods(session, user=user, query="arroz", limit=5)
    assert [food.source for food in foods] == ["taco", "tbca", "usda"]
