# macro-tracker — spec técnica (etapa 1: backend + MCP + CI/CD)

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
- Deploy: Vercel (Python runtime, free tier pessoal) — `api/index.py` expõe a app ASGI
- CI/CD: GitHub Actions (lint, mypy, migrations, testes) + deploy automático da Vercel via Git

## Layout

```
app/
  __init__.py
  main.py            # create_app(): monta REST + /mcp, /health
  config.py          # Settings (pydantic-settings)
  db.py              # engine async, sessionmaker, get_session dependency
  models.py          # ORM
  schemas.py         # pydantic (request/response)
  security.py        # hash/verify de tokens, resolução de usuário
  cli.py             # `python -m app.cli` (criar usuário/token)
  services/
    nutrition.py     # cálculo de macros por entrada e agregações diárias/por período
  routers/
    foods.py entries.py goals.py summary.py
  mcp/
    server.py        # MCPServer + tools
    auth.py          # middleware ASGI de bearer token + contextvar do usuário
alembic/ (env.py, versions/)
api/index.py         # entrypoint Vercel (`app = create_app()`)
tests/
vercel.json
.github/workflows/ci.yml
.github/workflows/migrate.yml
pyproject.toml, uv.lock, requirements.txt (exportado para a Vercel)
README.md
```

## Modelo de dados

Todas as tabelas com `id UUID PK default uuid4`, `created_at`/`updated_at timestamptz`.

- `users`: `email` (unique), `timezone` (text, default `America/Sao_Paulo`)
- `api_tokens`: `user_id FK`, `name`, `token_hash` (sha256 hex, unique), `last_used_at`,
  `revoked_at` nullable
- `foods`: `user_id FK nullable` (null = alimento global), `name`, `brand` nullable,
  nutrientes **por 100 g**: `kcal`, `protein_g`, `carbs_g`, `fat_g`, `fiber_g` nullable,
  `serving_label` nullable, `serving_grams` nullable.
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

`python -m app.cli create-user --email ... [--timezone ...]` e
`python -m app.cli create-token --email ... --name ...` (imprime o token em claro uma única vez).

## REST API (prefixo `/api`)

- `GET /health` — sem auth; `{"status":"ok"}` (não toca no banco)
- `POST /api/foods`, `GET /api/foods?search=&limit=` (busca case-insensitive por nome/brand,
  retorna alimentos do usuário + globais), `GET/PATCH/DELETE /api/foods/{id}`
- `POST /api/entries` (body: `logged_at?` default now, `meal`, `food_id?`, `description?`,
  `quantity_g?`, macros opcionais), `GET /api/entries?date=` ou `?from=&to=`,
  `PATCH/DELETE /api/entries/{id}`
- `PUT /api/goals` (upsert por `effective_from`, default hoje), `GET /api/goals/current?date=`,
  `GET /api/goals` (histórico)
- `GET /api/summary/daily?date=` → `{date, totals, goal, remaining, percent, entries_count,
  by_meal}`
- `GET /api/summary/range?from=&to=` → lista de dias + médias do período

404 quando o recurso é de outro usuário (nunca 403 vazando existência).

## Servidor MCP

Montado em `/mcp` (streamable HTTP, `stateless_http=True`, `json_response=True` — obrigatório em
serverless). Autenticação: middleware ASGI próprio na frente da app MCP, que valida o bearer token
e guarda o `user_id` num `contextvar` lido pelas tools. (Alternativa considerada: `token_verifier`
+ `AuthSettings` do SDK; exige configurar issuer/resource server OAuth, desnecessário aqui.)

Tools (nomes e descrições em inglês, para o agente; erros retornam mensagem clara, não stacktrace):

| tool | args | retorno |
|---|---|---|
| `log_food_entry` | `description?`, `food_id?`, `quantity_g?`, `meal?`, `logged_at?`, `kcal?`, `protein_g?`, `carbs_g?`, `fat_g?`, `fiber_g?`, `notes?` | entrada criada + resumo do dia |
| `list_entries` | `date?` ou `from`/`to` | entradas com macros |
| `delete_entry` | `entry_id` | ok |
| `search_foods` | `query`, `limit?` | alimentos com macros por 100 g |
| `create_food` | `name`, `brand?`, macros por 100 g, `serving_label?`, `serving_grams?` | alimento criado |
| `set_daily_goal` | `kcal`, `protein_g`, `carbs_g`, `fat_g`, `fiber_g?`, `effective_from?` | meta vigente |
| `get_daily_progress` | `date?` | consumido / meta / restante / % por macro |
| `get_range_summary` | `from`, `to` | totais por dia + médias |

Datas aceitas como `YYYY-MM-DD` e `logged_at` ISO-8601; ausente = agora no tz do usuário.

## Deploy / infra

- `vercel.json`: rewrite de todas as rotas para `api/index.py`; runtime Python 3.12.
- `requirements.txt` gerado por `uv export --no-dev --no-hashes` (a Vercel não lê `uv.lock`);
  CI falha se estiver fora de sincronia.
- Engine com `poolclass=NullPool` (serverless) e connection string **pooled** do Neon
  (`-pooler`), `?sslmode=require`; `statement_cache_size=0` no asyncpg por causa do pgbouncer.
- Env vars: `DATABASE_URL`, `APP_ENV`, `DEFAULT_TIMEZONE`, `LOG_LEVEL`.
- Migrations em prod: workflow `migrate.yml` (push em `main`) roda `alembic upgrade head` com o
  secret `DATABASE_URL`; faz skip com aviso se o secret não existir (repo recém-criado).

## CI

`.github/workflows/ci.yml` em PR e push em `main`:
1. `uv sync --all-extras --dev`
2. `ruff check .` + `ruff format --check .`
3. `mypy app tests`
4. `alembic upgrade head` contra o service Postgres 16 + `alembic check` (sem diff pendente)
5. `pytest -q` (mínimo: cálculo de macros, auth 401/escopo por usuário, CRUD de entries/foods,
   meta vigente por data, summary diário com e sem meta, handshake MCP + ao menos duas tools
   via HTTP)
6. verificação de `requirements.txt` sincronizado

## Fora de escopo nesta etapa

GUI web (etapa 2), busca em base pública de alimentos (ex. OpenFoodFacts), OAuth, multiusuário
com signup self-service.
