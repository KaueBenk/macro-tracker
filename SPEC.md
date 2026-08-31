# macro-tracker — spec técnica (etapa 2: backend + MCP + interface web + CI/CD)

App pessoal de contagem de macronutrientes e calorias, consumível por (a) agentes de IA via
servidor MCP remoto, (b) API REST (que a GUI web da etapa 2 vai usar).

## Stack

- Python 3.12, FastAPI, SQLAlchemy 2.0 (async, `asyncpg`), Alembic, pydantic v2 / pydantic-settings
- MCP: pacote `mcp>=2.1.1` (`from mcp.server.mcpserver import MCPServer`) — transporte
  streamable HTTP montado na mesma app FastAPI
- Gerenciador de pacotes: `uv` (pyproject.toml + uv.lock)
- Lint/format: `ruff` (check + format), tipos: `mypy`
- Testes: `pytest`, `pytest-asyncio`, `httpx.ASGITransport` contra Postgres local
- Banco: Postgres (Neon free tier em prod)
- Deploy: Vercel (Python runtime, free tier pessoal) — o preset FastAPI serve `app/main.py:app`
- CI/CD: GitHub Actions (lint, mypy, migrations, testes) + deploy automático da Vercel via Git

## Layout

```
app/
  __init__.py
  main.py            # create_app(): monta REST + /mcp, /app, /health
  config.py          # Settings (pydantic-settings)
  db.py              # engine async, sessionmaker, get_session dependency
  models.py          # ORM
  schemas.py         # pydantic (request/response)
  security.py        # hash/verify de tokens, resolução de usuário
  cli.py             # `python -m app.cli` (criar usuário/token)
  services/
    nutrition.py     # cálculo de macros por entrada e agregações diárias/por período
    food_search.py   # busca unificada, expiração e ranking por fonte/similaridade
    barcode.py       # lookup local/remoto por código de barras
  providers/
    base.py registry.py usda.py off.py # contratos, registry e providers remotos
  routers/
    foods.py entries.py goals.py summary.py account.py
  mcp/
    server.py        # MCPServer + tools
    auth.py          # middleware ASGI de bearer token + contextvar do usuário
  web/
    auth.py          # login Google, sessão de navegador e CSRF
  templates/         # páginas Jinja2 server-rendered
  static/            # CSS próprio, sem etapa de build
alembic/ (env.py, versions/)
tests/
.github/workflows/ci.yml
.github/workflows/migrate.yml
pyproject.toml, uv.lock
README.md
```

## Modelo de dados

Todas as tabelas com `id UUID PK default uuid4`, `created_at`/`updated_at timestamptz`.

- `users`: `email` (unique), `timezone` (text, default `America/Sao_Paulo`), `google_sub`
  (unique, nullable)
- `api_tokens`: `user_id FK`, `name`, `token_hash` (sha256 hex, unique), `last_used_at`,
  `revoked_at` nullable
- `foods`: `user_id FK nullable` (null = alimento global), `name`, `brand` nullable,
  nutrientes **por 100 g**: `kcal`, `protein_g`, `carbs_g`, `fat_g`, `fiber_g` nullable,
  `serving_label` nullable, `serving_grams` nullable, `source`, `source_ref`, `category` e
  `search_text`. `source`/`source_ref` identificam datasets globais e são protegidos contra
  duplicação; a API não permite que o usuário os defina. `source_version`, `attribution`,
  `barcode`, `locale`, `fetched_at`, `expires_at`, `archived_at` e `nutrients` guardam
  proveniência, cache e nutrientes extras. `dataset_versions` registra versões importadas,
  contagem, checksum e observações.
  Unique: `(user_id, lower(name), coalesce(brand,''))`
- `entries`: `user_id FK`, `logged_at timestamptz` (UTC), `meal` enum
  (`breakfast|lunch|dinner|snack|other`), `food_id FK nullable`, `description` nullable,
  `quantity_g` nullable, e os macros **já resolvidos** `kcal`, `protein_g`, `carbs_g`, `fat_g`,
  `fiber_g` nullable, `notes` nullable.
  Macros denormalizados porque um agente pode registrar entrada ad-hoc ("30 g de proteína no
  shake") sem alimento cadastrado; se `food_id` + `quantity_g` vierem, os macros são calculados
  no serviço e persistidos.
  Index: `(user_id, logged_at)`
- `goals`: `user_id FK`, `effective_from date`, `kcal`, `protein_g`, `carbs_g`, `fat_g`,
  `fiber_g` nullable. Unique `(user_id, effective_from)`.
  Meta vigente em D = a de maior `effective_from <= D` (histórico preservado).
- `web_login_states`: states de login Google para navegador, vinculados a um cookie temporário
  e expirados após 10 minutos.
- `web_sessions`: sessões de navegador com somente o hash do token, validade de 30 dias e
  atualização de `last_seen_at`.

Macros são `numeric(8,2)` no banco, expostos como `float` na API.

## Regras de negócio

- `resolve_entry_macros(food, quantity_g, overrides)`:
  - se `food_id` e `quantity_g`: macro = valor_por_100g * quantity_g / 100, arredondado a 2 casas;
  - overrides explícitos de macro sempre ganham do valor calculado;
  - se não há food nem nenhum macro explícito → erro 422.
- Dia local: `logged_at` é UTC; o "dia" usa o `timezone` do usuário (`zoneinfo`). Os limites do
  dia são calculados em Python e o filtro vai como range em UTC.
- Progresso da meta: `consumed`, `goal`, `remaining = goal - consumed`,
  `percent = round(consumed/goal*100, 1)` (0 se goal ausente/zero); `goal` pode ser `null` quando
  não há meta definida — nunca dividir por zero.

## Autenticação

Bearer token único para REST e MCP: `Authorization: Bearer <token>`.
Token gerado com `secrets.token_urlsafe(32)`, guardado apenas como `sha256`. Resolução:
hash → `api_tokens` (não revogado) → `users`. Atualiza `last_used_at` (best-effort, sem falhar a
request). 401 quando ausente/inválido. Todos os recursos são escopados pelo `user_id` do token.

O mesmo servidor também é um Authorization Server OAuth 2.1 para clientes MCP remotos:

- DCR em `POST /register` (RFC 7591).
- Metadados do AS em `/.well-known/oauth-authorization-server`.
- Metadados do recurso em `/.well-known/oauth-protected-resource/mcp` (RFC 9728).
- Authorization code com PKCE S256 em `/authorize` e `/token`.
- Access tokens de uma hora, refresh tokens rotativos de 30 dias e revogação em `/revoke`.
- Apenas hashes SHA-256 de códigos e tokens OAuth são persistidos.
- O `subject` do access token é o UUID do usuário, mantendo o isolamento multiusuário das
  tools MCP.

Os escopos aceitos são `mcp` e `ACCESS_VIEW_MANAGE_MCP_CONTENT`. O segundo é uma exigência
de compatibilidade de clientes Google e não concede nenhuma permissão adicional; não há
escopo obrigatório no resource server. Em desenvolvimento, `DevIdentityProvider` resolve
um usuário existente por e-mail (`email` na rota de login ou `DEV_LOGIN_EMAIL`). Em
produção, o login usa Google OIDC quando `GOOGLE_CLIENT_ID` e `GOOGLE_CLIENT_SECRET` estão
configurados. O callback usa o endpoint HTTPS `userinfo`, exige `email_verified=true` e não
valida assinatura de JWT localmente. Contas existentes são vinculadas por `google_sub` ou
e-mail; novas contas exigem `ALLOWED_EMAILS` e recebem `DEFAULT_TIMEZONE`. Sem configuração
Google, o login responde HTTP 503. Após autenticar, `OAUTH_REQUIRE_CONSENT` controla a tela
de consentimento server-rendered em português; a pending guarda o `user_id` autenticado até
a emissão do código e fica vinculada ao navegador do login por um cookie seguro de curta duração.

`python -m app.cli create-user --email ... [--timezone ...]` e
`python -m app.cli create-token --email ... --name ...` (imprime o token em claro uma única vez).

## REST API (prefixo `/api`)

- `GET /health` — sem auth; `{"status":"ok"}` (não toca no banco)
- `POST /api/foods`, `GET /api/foods?search=&limit=&sources=` (busca sem acentos, com todos os
  termos exigidos, por nome/brand/categoria; retorna alimentos do usuário + globais, ranqueados
  por prioridade de fonte e similaridade), `GET/PATCH/DELETE
  /api/foods/{id}`
- `POST /api/entries` (body: `logged_at?` default now, `meal`, `food_id?`, `description?`,
  `quantity_g?`, macros opcionais), `GET /api/entries?date=` ou `?from=&to=`,
  `PATCH/DELETE /api/entries/{id}`
- `PUT /api/goals` (upsert por `effective_from`, default hoje), `GET /api/goals/current?date=`,
  `GET /api/goals` (histórico)
- `GET /api/summary/daily?date=` → `{date, totals, goal, remaining, percent, entries_count,
  by_meal}`
- `GET /api/summary/range?from=&to=` → lista de dias + médias do período
- `GET /api/me` → id, e-mail e timezone do usuário autenticado
- `PATCH /api/me` → atualiza somente `timezone` (IANA/`zoneinfo`)

404 quando o recurso é de outro usuário (nunca 403 vazando existência).

## Servidor MCP

Montado em `/mcp` (streamable HTTP, `stateless_http=True`, `json_response=True` — obrigatório em
serverless). Autenticação: o verificador composto tenta primeiro access tokens OAuth e depois
os tokens estáticos legados. O middleware ASGI próprio guarda o `subject` (UUID do usuário)
num `contextvar` lido pelas tools. A configuração OAuth usa o `AuthSettings` e os handlers
de protocolo do SDK; a identidade humana permanece isolada atrás da interface
`IdentityProvider`.

Tools (nomes e descrições em inglês, para o agente; erros retornam mensagem clara, não stacktrace):

| tool | args | retorno |
|---|---|---|
| `log_food_entry` | `description?`, `food_id?`, `quantity_g?`, `meal?`, `logged_at?`, `kcal?`, `protein_g?`, `carbs_g?`, `fat_g?`, `fiber_g?`, `notes?` | entrada criada + resumo do dia |
| `list_entries` | `date?` ou `from`/`to` | entradas com macros |
| `delete_entry` | `entry_id` | ok |
| `search_foods` | `query`, `limit?`, `sources?`, `remote?` | alimentos com macros por 100 g |
| `lookup_food_barcode` | `barcode` | alimento por EAN/UPC, ou not found |
| `create_food` | `name`, `brand?`, macros por 100 g, `serving_label?`, `serving_grams?` | alimento criado |
| `set_daily_goal` | `kcal`, `protein_g`, `carbs_g`, `fat_g`, `fiber_g?`, `effective_from?` | meta vigente |
| `get_daily_progress` | `date?` | consumido / meta / restante / % por macro |
| `get_range_summary` | `from`, `to` | totais por dia + médias |

Datas aceitas como `YYYY-MM-DD` e `logged_at` ISO-8601; ausente = agora no tz do usuário.

Os alimentos globais incluem a Tabela Brasileira de Composição de Alimentos (TACO), 4ª edição,
do NEPA/UNICAMP (<https://nepa.unicamp.br/publicacoes/tabela-taco-excel/>), com atribuição e
citação obrigatórias à fonte. O dataset versionado em `data/taco.json` pode ser reconstruído
com `uv run --with openpyxl python scripts/build_taco_dataset.py` e importado com
`uv run python scripts/import_taco.py` (ou `--dry-run`).

A fundação de providers está em `app/providers/`: `ProviderFood`, `FoodProvider`,
`ProviderError`, um registry habilitável por `FOOD_PROVIDER_SOURCES` e a prioridade única
`privado > taco > tbca > usda > off > fatsecret`. A USDA FoodData Central é habilitada com
`USDA_FDC_API_KEY` (chave grátis em api.data.gov) e `FOOD_PROVIDER_SOURCES=usda`.
`remote=true` na busca REST ou MCP consulta fontes externas, pode levar alguns segundos e é
opt-in; a busca padrão usa apenas o cache local. Resultados USDA são materializados como
alimentos globais via cache-on-read, com TTL `NULL` porque CC0 permite cache indefinido.
Cada provider remoto usa `PROVIDER_TIMEOUT_SECONDS` (5 segundos por padrão); falhas não derrubam a busca e os resultados
válidos restantes são retornados.
O Open Food Facts e a TBCA são habilitados com `FOOD_PROVIDER_SOURCES=usda,off,tbca`;
configure `OFF_USER_AGENT`, `PROVIDER_TIMEOUT_SECONDS` e `TBCA_DETAIL_LIMIT`.
`GET /api/foods/barcode/{barcode}` e a tool `lookup_food_barcode` consultam primeiro o cache
local e depois o Open Food Facts por código de barras; a busca textual remota continua opt-in
e nunca deve ser usada como typeahead.
FatSecret é opcional e exige `FATSECRET_CLIENT_ID`, `FATSECRET_CLIENT_SECRET` e
`FOOD_PROVIDER_SOURCES=fatsecret`; `FATSECRET_DETAIL_LIMIT` limita os detalhes por busca.
O cache de nutrientes expira em 24 horas e é removido diariamente por
`.github/workflows/purge-cache.yml`, que depende do secret `DATABASE_URL` configurado no
GitHub.
Licenças, atribuições, limites e decisões para todas as fontes estão em
[`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md).

## Deploy / infra

- A Vercel detecta o preset FastAPI automaticamente e serve `app/main.py:app`; não há
  `vercel.json`. A versão do Python vem do `pyproject.toml` e as dependências do `uv.lock`.
- Engine com `poolclass=NullPool` (serverless) e connection string **pooled** do Neon
  (`-pooler`); o `DATABASE_URL` pode ser colado no formato original fornecido pelo Neon,
  pois scheme e parâmetros SSL são normalizados automaticamente. `statement_cache_size=0`
  no asyncpg é usado por causa do pgbouncer.
- Env vars na Vercel: `DATABASE_URL`, `APP_ENV`, `DEFAULT_TIMEZONE`, `LOG_LEVEL`,
  `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `ALLOWED_EMAILS`, `OAUTH_REQUIRE_CONSENT`,
  `FOOD_PROVIDER_SOURCES`, `USDA_FDC_API_KEY`, `OFF_USER_AGENT`, `PROVIDER_TIMEOUT_SECONDS`,
  `TBCA_DETAIL_LIMIT`, `FATSECRET_CLIENT_ID`, `FATSECRET_CLIENT_SECRET` e
  `FATSECRET_DETAIL_LIMIT`.
  `SERVERLESS` é detectado automaticamente quando a Vercel define `VERCEL`. Providers remotos
  futuros são habilitados por `FOOD_PROVIDER_SOURCES`.
- Para habilitar deploy automático via Git, o proprietário deve adicionar a conexão do GitHub
  em **Vercel > Account Settings > Login Connections** antes de executar `vercel git connect`.
- Migrations em prod: primeiro aplique localmente com
  `DATABASE_URL=<NEON_POOLED_DATABASE_URL> uv run alembic upgrade head`; depois o proprietário
  deve criar o secret `DATABASE_URL` em **GitHub Settings > Secrets and variables > Actions**
  para que o workflow `migrate.yml` (push em `main`) execute `alembic upgrade head`. Sem o
  secret, o workflow faz skip com aviso e sucesso.

## CI

`.github/workflows/ci.yml` em PR e push em `main`:
1. `uv sync --all-extras --dev`
2. `ruff check .` + `ruff format --check .`
3. `mypy app tests`
4. `alembic upgrade head` contra o service Postgres 16 + `alembic check` (sem diff pendente)
5. `pytest -q` (mínimo: cálculo de macros, auth 401/escopo por usuário, CRUD de entries/foods,
   meta vigente por data, summary diário com e sem meta, handshake MCP + ao menos duas tools
   via HTTP)

## Interface web (W1)

`GET /app` exige uma sessão de navegador iniciada em `GET /web/login`. O callback Google é
compartilhado com o fluxo MCP em `/oauth/google/callback` e despacha pelo state, preservando
as regras existentes de allowlist e `email_verified`. Logout em `POST /web/logout` exige um
token CSRF derivado por HMAC do token de sessão, usando `SECRET_KEY`; essa chave é obrigatória
em produção. A camada é server-rendered com Jinja2, HTMX e CSS próprio, sem SPA, bundle ou
build frontend. As páginas de produto serão adicionadas em etapas posteriores.
