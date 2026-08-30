import httpx
import pytest

from app.config import Settings
from app.providers.base import ProviderError
from app.providers.off import OFF_ATTRIBUTION, OFF_FIELDS, OFFProvider


def _product(**overrides: object) -> dict[str, object]:
    product: dict[str, object] = {
        "code": "7891234567890",
        "product_name": "Biscoito",
        "product_name_en": "Biscuit",
        "brands": "Marca, Outra",
        "categories": "Biscoitos, Snacks",
        "lang": "pt",
        "nutriments": {
            "energy-kcal_100g": 450,
            "proteins_100g": 7,
            "carbohydrates_100g": 65,
            "fat_100g": 18,
        },
    }
    product.update(overrides)
    return product


@pytest.mark.asyncio
async def test_off_fetch_parses_product_and_request_headers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"] == "test-agent"
        assert request.url.path == "/api/v3/product/7891234567890.json"
        assert request.url.params["fields"] == OFF_FIELDS
        return httpx.Response(200, json={"status": 1, "product": _product()})

    provider = OFFProvider(
        Settings(off_user_agent="test-agent"),
        transport=httpx.MockTransport(handler),
    )
    food = await provider.fetch_barcode("7891234567890")
    assert food is not None
    assert food.source_ref == "7891234567890"
    assert food.barcode == "7891234567890"
    assert food.brand == "Marca"
    assert food.category == "Biscoitos"
    assert food.locale == "pt"
    assert food.fiber_g is None
    assert food.attribution == OFF_ATTRIBUTION


@pytest.mark.asyncio
async def test_off_search_uses_v2_fields_and_parses_kj_fallback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v2/search"
        assert request.url.params["search_terms"] == "biscoito"
        assert request.url.params["page_size"] == "3"
        assert request.url.params["fields"] == OFF_FIELDS
        return httpx.Response(
            200,
            json={
                "products": [
                    _product(
                        product_name="",
                        nutriments={
                            "energy-kj_100g": 418.4,
                            "proteins_100g": 5,
                        },
                    ),
                    _product(
                        code="2",
                        product_name="Sem energia",
                        nutriments={"proteins_100g": 4},
                    ),
                ]
            },
        )

    provider = OFFProvider(
        Settings(off_user_agent="test-agent"),
        transport=httpx.MockTransport(handler),
    )
    foods = await provider.search("biscoito", 3)
    assert len(foods) == 1
    assert foods[0].name == "Biscuit"
    assert foods[0].kcal == pytest.approx(100)
    assert foods[0].protein_g == 5
    assert foods[0].carbs_g == 0


@pytest.mark.asyncio
async def test_off_barcode_not_found_and_provider_errors() -> None:
    async def fetch_status(status: int) -> OFFProvider:
        return OFFProvider(
            Settings(),
            transport=httpx.MockTransport(lambda _: httpx.Response(status)),
        )

    assert await (await fetch_status(404)).fetch_barcode("1") is None
    assert (
        await OFFProvider(
            Settings(),
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"status": 0})),
        ).fetch_barcode("1")
        is None
    )
    with pytest.raises(ProviderError):
        await (await fetch_status(429)).fetch_barcode("1")
    with pytest.raises(ProviderError):
        await (await fetch_status(503)).fetch_barcode("1")


@pytest.mark.asyncio
async def test_off_invalid_json_is_provider_error() -> None:
    provider = OFFProvider(
        Settings(),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"not-json")),
    )
    with pytest.raises(ProviderError, match="valid JSON"):
        await provider.fetch_barcode("1")


@pytest.mark.asyncio
async def test_off_network_error_is_provider_error() -> None:
    def network_failure(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed")

    provider = OFFProvider(Settings(), transport=httpx.MockTransport(network_failure))
    with pytest.raises(ProviderError, match="connection failed"):
        await provider.fetch_barcode("1")
