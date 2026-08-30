# Food data sources

This document records the license obligations and integration decisions for every
food-data source planned for Macro Tracker. Attribution is stored with each food
where the source requires it and is displayed by food search responses.

| Source | License / limits | Decision |
| --- | --- | --- |
| TACO 4 | Non-commercial use with mandatory citation to NEPA/UNICAMP. | Versioned repository dump in `data/taco.json`; import as global foods. |
| TBCA 7.3 | CC BY-NC-ND 4.0: no total or partial reproduction, commercial use, or alteration; mandatory citation. | Use only for this personal, non-commercial project; query on demand and write results directly into the private database without versioning or redistributing the data. |
| Open Food Facts | Database ODbL, contents DbCL, images CC BY-SA; attribution and share-alike obligations apply when publishing the database. | P3 API plus cache, primarily for barcodes; do not publish the database. Use v3 for products, v2 for search, and an identifying User-Agent. |
| USDA FoodData Central | CC0 1.0; citation suggested. API requires a free api.data.gov key and allows 1,000 requests/hour/IP. | API integration in P2 with opt-in `remote=true`; materialize results as global foods and cache indefinitely (`expires_at = NULL`). |
| FatSecret Basic | Free tier: 5,000 calls/day; US-only dataset; attribution required. Developer Terms prohibit caching user data over 24 hours except listed indefinitely storable IDs. | API integration planned for P5; nutrient rows expire after 24 hours and are purged by a job. The entry's macro snapshot is the user's own record. |

## TACO

The TACO 4th edition is published by NEPA/UNICAMP and was obtained from the
official spreadsheet at <https://nepa.unicamp.br/publicacoes/tabela-taco-excel/>
on 2026-08-29. The repository dump contains 591 items in `data/taco.json`.
Use and redistribution are non-commercial with mandatory attribution/citation to
NEPA/UNICAMP. Six spreadsheet foods were omitted because the source does not
quantify their calories: iogurte sabor abacaxi, leite de vaca desnatado UHT,
leite de vaca integral, sal dietético, sal grosso, and coco verde cru. When
calories are known, unquantified macros become `0`; `tr`/traço becomes `0`; and
unknown fiber remains `null`.

## TBCA

TBCA version 7.3 is published by USP / FoRC / BRASILFOODS at
<https://www.tbca.net.br/>. Its **CC BY-NC-ND 4.0** license prohibits total or
partial reproduction, commercial use, and alteration of the content. The
mandatory citation is:

> Tabela Brasileira de Composição de Alimentos (TBCA). Universidade de São Paulo
> (USP). Centro de Pesquisa em Alimentos (FoRC). Versão 7.3. São Paulo, 2025.
> Disponível em http://www.fcf.usp.br/tbca

There is no official API or dump for download. Because this is a personal,
non-commercial project, the decision is to use TBCA by writing data directly
to the user's private database. TBCA data is not versioned in this repository
and is not redistributed. The citation above is displayed with each food. The
project cannot be commercialized while the TBCA dataset is active. The provider
queries the site on demand only when the user explicitly requests a remote
search, materializes returned foods privately with an indefinite cache, and
never crawls the complete database. No TBCA data is included in this repository;
fixtures are synthetic markup and invented values only. This includes no bulk
importer or repository dump. Each remote search fetches at most
`TBCA_DETAIL_LIMIT` detail pages (default 5), with at most three detail
requests in flight and a 2.5-second timeout per TBCA request. The global
provider timeout is configurable with `PROVIDER_TIMEOUT_SECONDS` (5 seconds by
default). Remote search is opt-in (`remote=true`) and must not be used as
typeahead. Materialized TBCA foods use cache-on-read with `expires_at = NULL`.

## Open Food Facts

Open Food Facts uses ODbL for the database, DbCL for contents, and CC BY-SA for
images. Attribution is mandatory, and share-alike applies if we publish the
database; we do not publish it and instead consume the API and cache what the
user registers. The API limits are 15 requests/minute/IP for product reads and
10 requests/minute/IP for searches. Search must not be used as search-as-you-type.
For more than a few hundred products, Open Food Facts requests that consumers
use the dump. Requests must include a User-Agent identifying the app, version,
and contact. API v3 is recommended for product reads; it does not expose a
stable search endpoint, so this integration uses the available v2 search
endpoint for name queries. Product reads use
`GET /api/v3/product/{barcode}.json`; name search uses `GET /api/v2/search`
with restricted fields. Our decision is API plus indefinite cache (`ttl=None`),
with barcode as the primary use case and textual remote search only by explicit
request, never typeahead.

## USDA FoodData Central

USDA FoodData Central is **CC0 1.0** public-domain data and needs no permission.
The suggested citation is: “U.S. Department of Agriculture, Agricultural
Research Service. FoodData Central, 2019. fdc.nal.usda.gov”. Its API is
<https://api.nal.usda.gov/fdc/v1> and requires a free api.data.gov key. The
limit is 1,000 requests/hour/IP; exceeding it blocks the key for one hour.
Indefinite caching is allowed. Nutrient IDs to convert are 208 (kcal), 203
(protein), 204 (fat), and 205 (carbohydrate). In P2, enable it with
`USDA_FDC_API_KEY` and `FOOD_PROVIDER_SOURCES=usda`; `remote=true` explicitly
opts into the external request. The cache-on-read materializes the response as
a global `Food`, and USDA rows use `expires_at = NULL` because CC0 permits
indefinite caching. The provider never uses `labelNutrients`, which are
per-serving values rather than the required per-100-g values.

## FatSecret

FatSecret Basic is free for 5,000 calls/day, covers only the US dataset, and
requires attribution. Its Developer Terms prohibit caching user data for more
than 24 hours, except for fields listed as storable indefinitely, including
`food_id` and `serving_id` but not nutrients. The provider is planned for P5:
FatSecret food rows receive `expires_at = now + 24h` and a purge job removes
expired cache rows. The macro snapshot stored in a user's entry is the user's
own record, not redistribution of the FatSecret dataset. FatSecret can be
disabled through configuration if this interpretation is not acceptable.

## Operational obligations

- Display the applicable attribution alongside foods returned by search.
- Respect every source's rate limits and required request identification.
- Never use Open Food Facts search as typeahead; remote searches are explicit.
- Never redistribute TBCA data, and do not commercialize the project while TBCA
  is active.
- Use TBCA only on demand, never crawl the complete database, and display its
  citation with every materialized food.
- Purge expired FatSecret cache rows.
- Keep source version, fetch time, expiry, and archival metadata with imported
  foods so stale upstream data can be excluded without breaking existing entries.
