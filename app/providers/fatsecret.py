from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any

import httpx

from app.config import Settings
from app.providers.base import FoodProvider, ProviderError, ProviderFood

FATSECRET_ATTRIBUTION = "Powered by FatSecret Platform API (https://platform.fatsecret.com)"


class FatSecretProvider:
    source = "fatsecret"
    token_url = "https://oauth.fatsecret.com"
    api_url = "https://platform.fatsecret.com"

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.client_id = settings.fatsecret_client_id
        self.client_secret = settings.fatsecret_client_secret
        self.detail_limit = settings.fatsecret_detail_limit
        self._transport = transport
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    async def search(self, query: str, limit: int) -> list[ProviderFood]:
        payload = await self._api_request(
            {
                "method": "foods.search",
                "search_expression": query,
                "max_results": str(limit),
            }
        )
        foods = self._as_list(payload.get("foods"), "food")
        selected = foods[: min(limit, self.detail_limit)]
        semaphore = asyncio.Semaphore(3)

        async def parse_detail(item: Mapping[str, Any]) -> ProviderFood | None:
            food_id = item.get("food_id")
            if food_id is None:
                return None
            async with semaphore:
                detail = await self._api_request({"method": "food.get.v4", "food_id": str(food_id)})
            food = detail.get("food")
            return self._parse_food(food) if isinstance(food, Mapping) else None

        details = await asyncio.gather(*(parse_detail(item) for item in selected))
        return [food for food in details if food is not None]

    async def fetch(self, source_ref: str) -> ProviderFood | None:
        payload = await self._api_request({"method": "food.get.v4", "food_id": source_ref})
        food = payload.get("food")
        return self._parse_food(food) if isinstance(food, Mapping) else None

    async def _get_token(self) -> str:
        now = time.monotonic()
        if self._token is not None and now < self._token_expires_at:
            return self._token
        async with self._token_lock:
            now = time.monotonic()
            if self._token is not None and now < self._token_expires_at:
                return self._token
            try:
                async with httpx.AsyncClient(
                    base_url=self.token_url,
                    timeout=3.0,
                    auth=(self.client_id, self.client_secret),
                    transport=self._transport,
                ) as client:
                    response = await client.post(
                        "/connect/token",
                        data={"grant_type": "client_credentials", "scope": "basic"},
                    )
            except Exception as exc:
                raise ProviderError(f"FatSecret token request failed: {exc}") from exc
            payload = self._json_payload(response, "FatSecret token")
            token = payload.get("access_token")
            expires_in = self._number(payload.get("expires_in"))
            if not isinstance(token, str) or not token or expires_in is None:
                raise ProviderError("FatSecret token response did not contain a valid token")
            self._token = token
            self._token_expires_at = time.monotonic() + max(expires_in - 60.0, 0.0)
            return token

    async def _api_request(self, params: dict[str, str]) -> dict[str, Any]:
        token = await self._get_token()
        params = {**params, "format": "json"}
        try:
            async with httpx.AsyncClient(
                base_url=self.api_url,
                timeout=3.0,
                headers={"Authorization": f"Bearer {token}"},
                transport=self._transport,
            ) as client:
                response = await client.get("/rest/server.api", params=params)
        except Exception as exc:
            raise ProviderError(f"FatSecret API request failed: {exc}") from exc
        return self._json_payload(response, "FatSecret API")

    @staticmethod
    def _json_payload(response: httpx.Response, context: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception as exc:
            raise ProviderError(f"{context} response was not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ProviderError(f"{context} response was not a JSON object")
        error = payload.get("error")
        if response.is_error or isinstance(error, Mapping):
            message = error.get("message") if isinstance(error, Mapping) else None
            detail = str(message or response.text or response.reason_phrase)
            raise ProviderError(f"{context} request failed ({response.status_code}): {detail}")
        return payload

    @classmethod
    def _parse_food(cls, food: Mapping[str, Any]) -> ProviderFood | None:
        food_id = food.get("food_id")
        name = food.get("food_name")
        if food_id is None or not isinstance(name, str) or not name.strip():
            return None
        servings = cls._as_list(food.get("servings"), "serving")
        candidates: list[tuple[float, Mapping[str, Any]]] = []
        for serving in servings:
            if not isinstance(serving, Mapping):
                continue
            if str(serving.get("metric_serving_unit", "")).strip().lower() != "g":
                continue
            amount = cls._number(serving.get("metric_serving_amount"))
            if amount is not None and amount > 0:
                candidates.append((amount, serving))
        if not candidates:
            return None
        amount, serving = min(candidates, key=lambda candidate: candidate[0] != 100)
        calories = cls._number(serving.get("calories"))
        if calories is None:
            return None
        factor = 100 / amount
        fiber = cls._number(serving.get("fiber"))
        return ProviderFood(
            source=cls.source,
            source_ref=str(food_id),
            name=name.strip(),
            brand=food.get("brand_name") if isinstance(food.get("brand_name"), str) else None,
            locale="en-US",
            kcal=calories * factor,
            protein_g=(cls._number(serving.get("protein")) or 0.0) * factor,
            carbs_g=(cls._number(serving.get("carbohydrate")) or 0.0) * factor,
            fat_g=(cls._number(serving.get("fat")) or 0.0) * factor,
            fiber_g=fiber * factor if fiber is not None else None,
            attribution=FATSECRET_ATTRIBUTION,
            source_version=(
                food.get("food_type") if isinstance(food.get("food_type"), str) else None
            ),
        )

    @staticmethod
    def _as_list(value: object, key: str) -> list[Any]:
        if not isinstance(value, Mapping):
            return []
        nested = value.get(key)
        if isinstance(nested, list):
            return nested
        return [nested] if nested is not None else []

    @staticmethod
    def _number(value: object) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        if not isinstance(value, int | float | str):
            return None
        try:
            return float(value)
        except ValueError:
            return None


def fatsecret_factory(settings: Settings) -> FoodProvider | None:
    if not settings.fatsecret_client_id or not settings.fatsecret_client_secret:
        return None
    return FatSecretProvider(settings)
