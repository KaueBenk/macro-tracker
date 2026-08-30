from typing import Protocol

from pydantic import BaseModel


class ProviderFood(BaseModel):
    """Food returned by a provider, with nutrition values per 100 g."""

    source: str
    source_ref: str
    name: str
    brand: str | None = None
    category: str | None = None
    barcode: str | None = None
    locale: str | None = None
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float | None = None
    attribution: str
    source_version: str | None = None
    nutrients: dict[str, float] | None = None


class FoodProvider(Protocol):
    source: str

    async def search(self, query: str, limit: int) -> list[ProviderFood]: ...

    async def fetch(self, source_ref: str) -> ProviderFood | None: ...


class ProviderError(Exception):
    """Raised when a food provider cannot fulfill a request."""
