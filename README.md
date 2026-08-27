# macro-tracker

API pessoal para acompanhar calorias e macronutrientes, com FastAPI, PostgreSQL e uma
camada de autenticação por bearer token. O servidor MCP será adicionado na próxima etapa.

## Desenvolvimento local

Requisitos: Python 3.12, [uv](https://docs.astral.sh/uv/) e PostgreSQL 16.

```bash
uv python install 3.12
createdb macro_tracker_test
uv sync --dev
cp .env.example .env
uv run alembic upgrade head
```

O `.env.example` usa:

| Variável | Descrição | Exemplo |
| --- | --- | --- |
| `DATABASE_URL` | URL async do PostgreSQL | `postgresql+asyncpg://postgres:postgres@localhost:5432/macro_tracker_test` |
| `APP_ENV` | Ambiente da aplicação | `development` |
| `DEFAULT_TIMEZONE` | Fuso horário padrão de novos usuários | `America/Sao_Paulo` |
| `LOG_LEVEL` | Nível de log | `INFO` |
| `SERVERLESS` | Habilita `NullPool` e configurações do pgbouncer | `false` |

Crie um usuário e um token (o token é impresso uma única vez):

```bash
uv run python -m app.cli create-user --email voce@example.com --timezone America/Sao_Paulo
uv run python -m app.cli create-token --email voce@example.com --name local
```

Execute a API e os testes:

```bash
uv run uvicorn app.main:app --reload
uv run pytest -q
```

A API fica em `http://localhost:8000`; `GET /health` não exige autenticação.
Os endpoints REST autenticados usam `Authorization: Bearer <token>`, por exemplo:

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/summary/daily
```

Lint, tipos e migrações:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app tests
uv run alembic check
```
