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
- Deploy: Vercel (Python runtime, free tier pessoal) — o preset FastAPI serve `app/main.py:app`
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
tests/
.github/workflows/ci.yml
.github/workflows/migrate.yml
pyproject.toml, uv.lock
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
produção essa seam responde HTTP 503 até que o provedor de identidade Google seja integrado.

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
| `search_foods` | `query`, `limit?` | alimentos com macros por 100 g |
| `create_food` | `name`, `brand?`, macros por 100 g, `serving_label?`, `serving_grams?` | alimento criado |
| `set_daily_goal` | `kcal`, `protein_g`, `carbs_g`, `fat_g`, `fiber_g?`, `effective_from?` | meta vigente |
| `get_daily_progress` | `date?` | consumido / meta / restante / % por macro |
| `get_range_summary` | `from`, `to` | totais por dia + médias |

Datas aceitas como `YYYY-MM-DD` e `logged_at` ISO-8601; ausente = agora no tz do usuário.

## Deploy / infra

- A Vercel detecta o preset FastAPI automaticamente e serve `app/main.py:app`; não há
  `vercel.json`. A versão do Python vem do `pyproject.toml` e as dependências do `uv.lock`.
- Engine com `poolclass=NullPool` (serverless) e connection string **pooled** do Neon
  (`-pooler`); o `DATABASE_URL` pode ser colado no formato original fornecido pelo Neon,
  pois scheme e parâmetros SSL são normalizados automaticamente. `statement_cache_size=0`
  no asyncpg é usado por causa do pgbouncer.
- Env vars na Vercel: `DATABASE_URL`, `APP_ENV`, `DEFAULT_TIMEZONE` e `LOG_LEVEL`.
  `SERVERLESS` é detectado automaticamente quando a Vercel define `VERCEL`.
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

## Fora de escopo nesta etapa

GUI web (etapa 2), busca em base pública de alimentos (ex. OpenFoodFacts), login Google e
signup self-service.
