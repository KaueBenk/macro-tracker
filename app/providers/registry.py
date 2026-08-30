from app.config import Settings, get_settings
from app.providers.base import FoodProvider

SOURCE_PRIORITY: dict[str | None, int] = {
    None: 9,
    "taco": 1,
    "tbca": 2,
    "usda": 3,
    "off": 4,
    "fatsecret": 5,
}

_providers: dict[str, FoodProvider] = {}


def register_provider(provider: FoodProvider) -> None:
    _providers[provider.source] = provider


def get_enabled_providers(settings: Settings | None = None) -> dict[str, FoodProvider]:
    active_settings = settings or get_settings()
    enabled = {
        source.strip().lower()
        for source in active_settings.food_provider_sources.split(",")
        if source.strip()
    }
    return {source: provider for source, provider in _providers.items() if source in enabled}
