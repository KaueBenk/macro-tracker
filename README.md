# macro-tracker

API pessoal para acompanhar calorias e macronutrientes, com FastAPI, PostgreSQL,
autenticação por bearer token e servidor MCP para agentes.

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

## Deploy com Neon e Vercel

1. No [Neon](https://neon.tech), crie uma conta gratuita, selecione **New project**,
   escolha a região desejada e copie a conexão **pooled** (`-pooler`) com SSL.
2. No dashboard da Vercel, selecione **Add New... > Project**, importe este repositório
   do GitHub e mantenha o framework como **Other**. Em **Settings > Environment Variables**,
   adicione:
   - `DATABASE_URL`: URL pooled do Neon, incluindo `?sslmode=require`
   - `APP_ENV`: `production`
   - `DEFAULT_TIMEZONE`: por exemplo `America/Sao_Paulo`
   - `LOG_LEVEL`: `INFO`
   - `SERVERLESS`: opcional; `true` é detectado automaticamente quando a Vercel define
     `VERCEL`, mas pode ser configurado explicitamente
3. Clique em **Deploy**. Pushes na branch conectada geram novos deploys automaticamente.
4. Para executar as migrações no banco de produção, abra o GitHub em
   **Settings > Secrets and variables > Actions > New repository secret**, crie o segredo
   `DATABASE_URL` com a mesma URL pooled do Neon e faça push em `main`. O workflow
   `migrate.yml` executa `alembic upgrade head`; sem o segredo, ele encerra com aviso e
   sucesso para não deixar a branch vermelha.

## MCP

O endpoint remoto é `https://<seu-app>.vercel.app/mcp`. O cliente MCP deve enviar o mesmo
bearer token usado pela API REST:

```json
{
  "mcpServers": {
    "macro-tracker": {
      "url": "https://<seu-app>.vercel.app/mcp",
      "headers": {
        "Authorization": "Bearer <TOKEN>"
      }
    }
  }
}
```

Gere um token localmente (ou em um ambiente com `DATABASE_URL` apontando para o Neon):

```bash
uv run python -m app.cli create-token --email voce@example.com --name agente
```

O token é exibido uma única vez. As tools aceitam datas locais em `YYYY-MM-DD`, timestamps
`logged_at` em ISO-8601 e macros em gramas; os nutrientes cadastrados em alimentos são por
100 g.
