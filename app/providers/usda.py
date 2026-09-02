from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import httpx

from app.config import Settings
from app.providers.base import FoodProvider, ProviderError, ProviderFood

USDA_ATTRIBUTION = (
    "U.S. Department of Agriculture, Agricultural Research Service. "
    "FoodData Central, 2019. fdc.nal.usda.gov"
)
logger = logging.getLogger(__name__)


class USDAProvider:
    source = "usda"
    base_url = "https://api.nal.usda.gov/fdc/v1"

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = settings.usda_api_key
        self._transport = transport

    async def search(self, query: str, limit: int) -> list[ProviderFood]:
        try:
            response = await self._request(
                "POST",
                "/foods/search",
                json={
                    "query": query,
                    "pageSize": limit,
                    "dataType": ["Foundation", "SR Legacy", "Branded"],
                },
            )
            payload = self._payload(response)
            foods = payload.get("foods")
            if not isinstance(foods, list):
                raise ProviderError("USDA response did not contain a foods list")
            parsed: list[ProviderFood] = []
            for item in foods:
                try:
                    food = self._parse_food(item)
                except ProviderError as exc:
                    self._log_malformed_item(exc)
                    continue
                if food is not None:
                    parsed.append(food)
            return parsed
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"USDA search failed: {exc}") from exc

    async def fetch(self, source_ref: str) -> ProviderFood | None:
        try:
            response = await self._request("GET", f"/food/{source_ref}")
            payload = self._payload(response)
            return self._parse_food(payload)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"USDA fetch failed: {exc}") from exc

    @staticmethod
    def _log_malformed_item(error: ProviderError) -> None:
        logger.debug("Ignoring malformed USDA food item: %s", error)

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        params = {"api_key": self.api_key}
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=3.0,
                transport=self._transport,
            ) as client:
                response = await client.request(method, path, params=params, **kwargs)
        except Exception as exc:
            raise ProviderError(f"USDA request failed: {exc}") from exc
        if response.status_code in {403, 429}:
            raise ProviderError(self._error_message(response))
        if response.is_error:
            raise ProviderError(self._error_message(response))
        return response

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, Mapping):
                for key in ("message", "error", "errorMessage"):
                    value = payload.get(key)
                    if isinstance(value, Mapping):
                        value = value.get("message")
                    if value:
                        return f"USDA request failed ({response.status_code}): {value}"
        except ValueError:
            pass
        detail = response.text.strip() or response.reason_phrase
        return f"USDA request failed ({response.status_code}): {detail}"

    @staticmethod
    def _payload(response: httpx.Response) -> dict[str, Any]:
        payload = response.json()
        if not isinstance(payload, dict):
            raise ProviderError("USDA response was not a JSON object")
        return payload

    @classmethod
    def _parse_food(cls, item: object) -> ProviderFood | None:
        if not isinstance(item, dict):
            raise ProviderError("USDA food item was not an object")
        source_ref = item.get("fdcId")
        name = item.get("description")
        if source_ref is None or not isinstance(name, str) or not name:
            raise ProviderError("USDA food item is missing fdcId or description")

        amounts, extras = cls._nutrients(item.get("foodNutrients"))
        kcal = amounts.get("208")
        if kcal is None:
            kcal = amounts.get("957")
        if kcal is None:
            kcal = amounts.get("958")
        if kcal is None and amounts.get("268") is not None:
            kcal = amounts["268"] / 4.184
        if kcal is None:
            return None

        data_type = item.get("dataType")
        category = item.get("foodCategory")
        brand = item.get("brandName") or item.get("brandOwner")
        barcode = item.get("gtinUpc")
        return ProviderFood(
            source=cls.source,
            source_ref=str(source_ref),
            name=name,
            brand=brand if isinstance(brand, str) else None,
            category=category if isinstance(category, str) else None,
            barcode=str(barcode) if barcode is not None else None,
            locale="en-US",
            kcal=float(kcal),
            protein_g=float(amounts.get("203", 0.0)),
            carbs_g=float(amounts.get("205", 0.0)),
            fat_g=float(amounts.get("204", 0.0)),
            fiber_g=float(amounts["291"]) if amounts.get("291") is not None else None,
            attribution=USDA_ATTRIBUTION,
            source_version=data_type if isinstance(data_type, str) else None,
            nutrients=extras or None,
        )

    @staticmethod
    def _nutrients(raw: object) -> tuple[dict[str, float], dict[str, float]]:
        if not isinstance(raw, list):
            raise ProviderError("USDA food item is missing foodNutrients")
        amounts: dict[str, float] = {}
        extras: dict[str, float] = {}
        known = {"203", "204", "205", "208", "268", "291", "957", "958"}
        for nutrient in raw:
            if not isinstance(nutrient, dict):
                continue
            number = nutrient.get("nutrientNumber")
            if number is None:
                nested = nutrient.get("nutrient")
                if isinstance(nested, dict):
                    number = nested.get("number")
            if number is None:
                continue
            value = nutrient.get("value", nutrient.get("amount"))
            if isinstance(value, bool) or not isinstance(value, int | float):
                continue
            number_string = str(number)
            amounts[number_string] = float(value)
            if number_string not in known:
                extras[number_string] = float(value)
        return amounts, extras


def usda_factory(settings: Settings) -> FoodProvider | None:
    if not settings.usda_api_key:
        return None
    return USDAProvider(settings)
