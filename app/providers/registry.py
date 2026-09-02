from collections.abc import Callable

from app.config import Settings, get_settings
from app.providers.base import FoodProvider
from app.providers.fatsecret import fatsecret_factory
from app.providers.off import off_factory
from app.providers.tbca import tbca_factory
from app.providers.usda import usda_factory

SOURCE_PRIORITY: dict[str | None, int] = {
    None: 9,
    "taco": 1,
    "tbca": 2,
    "usda": 3,
    "off": 4,
    "fatsecret": 5,
}

ProviderFactory = Callable[[Settings], FoodProvider | None]

_provider_factories: dict[str, ProviderFactory] = {
    "fatsecret": fatsecret_factory,
    "off": off_factory,
    "tbca": tbca_factory,
    "usda": usda_factory,
}


def register_provider(source: str, factory: ProviderFactory) -> None:
    _provider_factories[source.lower()] = factory


def get_enabled_providers(settings: Settings | None = None) -> dict[str, FoodProvider]:
    active_settings = settings or get_settings()
    enabled = {
        source.strip().lower()
        for source in active_settings.food_provider_sources.split(",")
        if source.strip()
    }
    providers: dict[str, FoodProvider] = {}
    for source in enabled:
        factory = _provider_factories.get(source)
        if factory is None:
            continue
        provider = factory(active_settings)
        if provider is not None:
            providers[source] = provider
    return providers
