from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from app.config import Settings
from app.providers.base import FoodProvider, ProviderError, ProviderFood

OFF_ATTRIBUTION = "Open Food Facts contributors, openfoodfacts.org (ODbL)"
OFF_FIELDS = "code,product_name,product_name_en,brands,categories,nutriments,lang"


class OFFProvider:
    source = "off"
    base_url = "https://world.openfoodfacts.org"

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.user_agent = settings.off_user_agent
        self._transport = transport

    async def search(self, query: str, limit: int) -> list[ProviderFood]:
        response = await self._request(
            "GET",
            "/api/v2/search",
            params={
                "search_terms": query,
                "page_size": limit,
                "fields": OFF_FIELDS,
            },
        )
        payload = self._payload(response)
        products = payload.get("products")
        if not isinstance(products, list):
            raise ProviderError("Open Food Facts response did not contain a products list")
        parsed: list[ProviderFood] = []
        for product in products:
            if not isinstance(product, dict):
                raise ProviderError("Open Food Facts product was not an object")
            food = self._parse_product(product)
            if food is not None:
                parsed.append(food)
        return parsed

    async def fetch(self, source_ref: str) -> ProviderFood | None:
        return await self.fetch_barcode(source_ref)

    async def fetch_barcode(self, barcode: str) -> ProviderFood | None:
        try:
            response = await self._request(
                "GET",
                f"/api/v3/product/{barcode}.json",
                params={"fields": OFF_FIELDS},
                not_found_ok=True,
            )
        except _OFFNotFound:
            return None
        payload = self._payload(response)
        if payload.get("status") == 0 or not isinstance(payload.get("product"), dict):
            return None
        return self._parse_product(payload["product"])

    async def _request(
        self, method: str, path: str, *, not_found_ok: bool = False, **kwargs: Any
    ) -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=3.0,
                headers={"User-Agent": self.user_agent},
                transport=self._transport,
            ) as client:
                response = await client.request(method, path, **kwargs)
        except Exception as exc:
            raise ProviderError(f"Open Food Facts request failed: {exc}") from exc
        if response.status_code == 404 and not_found_ok:
            raise _OFFNotFound
        if response.status_code == 404:
            raise ProviderError(self._error_message(response))
        if response.status_code in {429, 503} or response.is_error:
            raise ProviderError(self._error_message(response))
        return response

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, Mapping):
                for key in ("message", "error"):
                    value = payload.get(key)
                    if isinstance(value, Mapping):
                        value = value.get("message")
                    if value:
                        return f"Open Food Facts request failed ({response.status_code}): {value}"
        except ValueError:
            pass
        detail = response.text.strip() or response.reason_phrase
        return f"Open Food Facts request failed ({response.status_code}): {detail}"

    @staticmethod
    def _payload(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception as exc:
            raise ProviderError(f"Open Food Facts response was not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ProviderError("Open Food Facts response was not a JSON object")
        return payload

    @classmethod
    def _parse_product(cls, product: dict[str, Any]) -> ProviderFood | None:
        code = product.get("code")
        if code is None:
            return None
        name = product.get("product_name") or product.get("product_name_en")
        if not isinstance(name, str) or not name.strip():
            return None
        nutriments = product.get("nutriments")
        if not isinstance(nutriments, dict):
            return None
        kcal = cls._number(nutriments.get("energy-kcal_100g"))
        if kcal is None:
            energy_kj = cls._number(nutriments.get("energy-kj_100g"))
            kcal = energy_kj / 4.184 if energy_kj is not None else None
        if kcal is None:
            return None
        brand = cls._first_label(product.get("brands"))
        category = cls._first_label(product.get("categories"))
        lang = product.get("lang")
        return ProviderFood(
            source=cls.source,
            source_ref=str(code),
            name=name.strip(),
            brand=brand,
            category=category,
            barcode=str(code),
            locale=lang if isinstance(lang, str) else None,
            kcal=kcal,
            protein_g=cls._number(nutriments.get("proteins_100g")) or 0.0,
            carbs_g=cls._number(nutriments.get("carbohydrates_100g")) or 0.0,
            fat_g=cls._number(nutriments.get("fat_100g")) or 0.0,
            fiber_g=cls._number(nutriments.get("fiber_100g")),
            attribution=OFF_ATTRIBUTION,
        )

    @staticmethod
    def _number(value: object) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        if not isinstance(value, int | float | str):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _first_label(value: object) -> str | None:
        if isinstance(value, list):
            value = value[0] if value else None
        if not isinstance(value, str):
            return None
        label = value.split(",", 1)[0].strip()
        return label or None


class _OFFNotFound(Exception):
    pass


def off_factory(settings: Settings) -> FoodProvider | None:
    return OFFProvider(settings)
