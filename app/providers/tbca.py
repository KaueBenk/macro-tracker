from __future__ import annotations

import asyncio
import re
from html.parser import HTMLParser
from typing import Any

import httpx

from app.config import Settings
from app.providers.base import FoodProvider, ProviderError, ProviderFood

TBCA_ATTRIBUTION = (
    "Tabela Brasileira de Composição de Alimentos (TBCA). Universidade de São Paulo (USP). "
    "Centro de Pesquisa em Alimentos (FoRC). Versão 7.3. São Paulo, 2025. "
    "Disponível em http://www.fcf.usp.br/tbca"
)


class _ListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, str, str, str]] = []
        self._in_table = False
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._links: list[str] = []
        self.saw_table = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._in_table = True
            self.saw_table = True
        elif self._in_table and tag == "tr":
            self._row = []
            self._links = []
        elif self._row is not None and tag in {"td", "th"}:
            self._cell = []
        elif self._cell is not None and tag == "a":
            href = dict(attrs).get("href")
            if href is not None:
                self._links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(_clean_text("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if len(self._row) >= 4 and self._links:
                href = self._links[0]
                query = href.split("?", 1)[1] if "?" in href else ""
                if query and self._row[0]:
                    self.rows.append((self._row[0], query, self._row[1], self._row[3]))
            self._row = None
        elif tag == "table":
            self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


class _DetailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, str, str]] = []
        self._in_table = False
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self.saw_table = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table" and dict(attrs).get("id") == "tabela1":
            self._in_table = True
            self.saw_table = True
        elif self._in_table and tag == "tr":
            self._row = []
        elif self._row is not None and tag in {"td", "th"}:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(_clean_text("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if len(self._row) >= 3:
                self.rows.append((self._row[0], self._row[1], self._row[2]))
            self._row = None
        elif tag == "table" and self._in_table:
            self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _parse_number(value: str) -> float | None:
    normalized = value.strip().lower()
    if normalized in {"", "na", "-", "—", "tr", "traço"}:
        return 0.0 if normalized in {"tr", "traço"} else None
    if "," in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return None


class TBCAProvider:
    source = "tbca"
    base_url = "https://www.tbca.net.br"

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.detail_limit = settings.tbca_detail_limit
        self.user_agent = settings.off_user_agent
        self._transport = transport

    async def search(self, query: str, limit: int) -> list[ProviderFood]:
        listings = await self._listing(query)
        selected = listings[: min(limit, self.detail_limit)]
        semaphore = asyncio.Semaphore(3)

        async def parse_detail(listing: tuple[str, str, str, str]) -> ProviderFood | None:
            async with semaphore:
                html = await self._request(
                    "GET",
                    f"/base-dados/int_composicao_alimentos.php?{listing[1]}",
                )
            return self._parse_detail(listing, html)

        details = await asyncio.gather(*(parse_detail(item) for item in selected))
        return [food for food in details if food is not None]

    async def fetch(self, source_ref: str) -> ProviderFood | None:
        listings = await self._listing(source_ref)
        for listing in listings:
            if listing[0] == source_ref:
                html = await self._request(
                    "GET",
                    f"/base-dados/int_composicao_alimentos.php?{listing[1]}",
                )
                return self._parse_detail(listing, html)
        return None

    async def _listing(self, query: str) -> list[tuple[str, str, str, str]]:
        html = await self._request(
            "POST",
            "/base-dados/composicao_alimentos.php",
            data={"guarda": "tomo1", "produto": query},
        )
        parser = _ListingParser()
        try:
            parser.feed(html)
            parser.close()
        except Exception as exc:
            raise ProviderError(f"TBCA listing HTML could not be parsed: {exc}") from exc
        if not parser.saw_table:
            raise ProviderError("TBCA listing response did not contain a table")
        return parser.rows

    @classmethod
    def _parse_detail(cls, listing: tuple[str, str, str, str], html: str) -> ProviderFood | None:
        parser = _DetailParser()
        try:
            parser.feed(html)
            parser.close()
        except Exception as exc:
            raise ProviderError(f"TBCA detail HTML could not be parsed: {exc}") from exc
        if not parser.saw_table:
            raise ProviderError("TBCA detail response did not contain tabela1")

        energy_kcal: float | None = None
        energy_kj: float | None = None
        values: dict[str, float | None] = {}
        for component, unit, value in parser.rows:
            number = _parse_number(value)
            component = _clean_text(component)
            unit = _clean_text(unit).lower()
            if component == "Energia":
                if unit == "kcal":
                    energy_kcal = number
                elif unit == "kj":
                    energy_kj = number
            elif component in {
                "Proteína",
                "Lipídios",
                "Carboidrato total",
                "Fibra alimentar",
            }:
                values[component] = number
        kcal = energy_kcal
        if kcal is None and energy_kj is not None:
            kcal = energy_kj / 4.184
        if kcal is None:
            return None
        category = listing[3].split(" - ", 1)[-1].strip() or None
        return ProviderFood(
            source=cls.source,
            source_ref=listing[0],
            name=listing[2],
            category=category,
            locale="pt-BR",
            kcal=kcal,
            protein_g=values.get("Proteína") or 0.0,
            carbs_g=values.get("Carboidrato total") or 0.0,
            fat_g=values.get("Lipídios") or 0.0,
            fiber_g=values.get("Fibra alimentar"),
            attribution=TBCA_ATTRIBUTION,
            source_version="TBCA 7.3",
        )

    async def _request(self, method: str, path: str, **kwargs: Any) -> str:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=2.5,
                headers={"User-Agent": self.user_agent},
                transport=self._transport,
            ) as client:
                response = await client.request(method, path, **kwargs)
        except Exception as exc:
            raise ProviderError(f"TBCA request failed: {exc}") from exc
        if response.is_error:
            detail = response.text.strip() or response.reason_phrase
            raise ProviderError(f"TBCA request failed ({response.status_code}): {detail}")
        return response.text


def tbca_factory(settings: Settings) -> FoodProvider | None:
    return TBCAProvider(settings)
