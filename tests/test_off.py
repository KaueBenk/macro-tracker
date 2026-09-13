import httpx
import pytest

from app.config import Settings
from app.providers.base import ProviderError
from app.providers.off import OFF_ATTRIBUTION, OFF_FIELDS, OFF_SEARCH_FIELDS, OFFProvider


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
async def test_off_search_uses_search_api_and_parses_kj_fallback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "search.openfoodfacts.org"
        assert request.url.path == "/search"
        assert request.url.params["q"] == 'biscoito countries_tags:"en:brazil"'
        assert request.url.params["page_size"] == "3"
        assert request.url.params["fields"] == OFF_SEARCH_FIELDS
        return httpx.Response(
            200,
            json={
                "hits": [
                    {
                        "code": "2",
                        "product_name": "Arroz parboilizado",
                        "brands": ["Arroz Selecto"],
                        "categories_tags": ["en:plant-based-foods", "en:parboiled-rices"],
                        "countries_tags": ["en:brazil"],
                        "lang": "pt",
                        "nutriments": {
                            "energy-kj_100g": 418.4,
                            "proteins_100g": 5,
                            "carbohydrates_100g": 20,
                            "fat_100g": 1,
                            "fiber_100g": 2,
                        },
                    },
                    {"code": "3", "product_name": None, "nutriments": {}},
                    {"code": "4", "product_name": "Sem nutrientes"},
                ]
            },
        )

    provider = OFFProvider(
        Settings(off_user_agent="test-agent"),
        transport=httpx.MockTransport(handler),
    )
    foods = await provider.search("biscoito", 3)
    assert len(foods) == 1
    assert foods[0].name == "Arroz parboilizado"
    assert foods[0].brand == "Arroz Selecto"
    assert foods[0].category == "parboiled rices"
    assert foods[0].source_ref == "2"
    assert foods[0].barcode == "2"
    assert foods[0].locale == "pt"
    assert foods[0].kcal == pytest.approx(100)
    assert foods[0].protein_g == 5
    assert foods[0].carbs_g == 20
    assert foods[0].fat_g == 1
    assert foods[0].fiber_g == 2


@pytest.mark.asyncio
async def test_off_search_sanitizes_query_and_skips_empty_queries() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"hits": []})

    provider = OFFProvider(Settings(), transport=httpx.MockTransport(handler))
    assert await provider.search('+ - && || ! ( ) { } [ ] ^ " ~ * ? : \\ /', 3) == []
    assert requests == []
    await provider.search('arroz "integral"', 3)
    assert requests[0].url.params["q"] == 'arroz integral countries_tags:"en:brazil"'


@pytest.mark.asyncio
async def test_off_search_retries_rate_limit_once() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"hits": []})

    provider = OFFProvider(Settings(), transport=httpx.MockTransport(handler))
    assert await provider.search("arroz", 3) == []
    assert calls == 2


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
