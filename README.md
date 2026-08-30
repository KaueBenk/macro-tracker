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
| `PUBLIC_BASE_URL` | URL pública usada pelo OAuth e pelos metadados MCP | `http://localhost:8000` |
| `SERVERLESS` | Habilita `NullPool` e configurações do pgbouncer | `false` |
| `DEV_LOGIN_EMAIL` | E-mail usado pelo login OAuth de desenvolvimento | `voce@example.com` |
| `GOOGLE_CLIENT_ID` | Client ID OAuth do Google (produção) | — |
| `GOOGLE_CLIENT_SECRET` | Client secret OAuth do Google (produção) | — |
| `ALLOWED_EMAILS` | E-mails permitidos para criar novas contas, separados por vírgula | — |
| `OAUTH_REQUIRE_CONSENT` | Exibe a tela de consentimento após o login | `true` |
| `FOOD_PROVIDER_SOURCES` | Providers remotos habilitados, separados por vírgula | `usda` |
| `USDA_FDC_API_KEY` | Chave grátis do USDA FoodData Central obtida em api.data.gov | — |
| `OFF_USER_AGENT` | User-Agent exigido pelo Open Food Facts | `macro-tracker/0.1 (https://github.com/KaueBenk/macro-tracker)` |
| `PROVIDER_TIMEOUT_SECONDS` | Timeout dos providers remotos | `5.0` |
| `TBCA_DETAIL_LIMIT` | Máximo de detalhes TBCA por busca | `5` |

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

Os alimentos globais incluem a Tabela Brasileira de Composição de Alimentos (TACO),
4ª edição, do NEPA/UNICAMP (<https://nepa.unicamp.br/publicacoes/tabela-taco-excel/>).
Atribua e cite o NEPA/UNICAMP ao utilizar esses dados. A busca ignora acentos e exige
todos os termos informados, permitindo encontrar alimentos brasileiros como `feijao`
e `arroz integral`; alimentos cadastrados pelo usuário aparecem antes dos globais.
Para reconstruir o dataset, use `uv run --with openpyxl python scripts/build_taco_dataset.py`;
para importá-lo ou atualizá-lo no banco, use `uv run python scripts/import_taco.py`
(ou `--dry-run`).

As licenças e decisões de integração das fontes TACO, TBCA, Open Food Facts, USDA FoodData
Central e FatSecret estão em [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md). Para habilitar o
provider USDA, obtenha uma chave grátis em [api.data.gov](https://api.data.gov/), configure
`USDA_FDC_API_KEY` e use `FOOD_PROVIDER_SOURCES=usda`. A busca remota é opt-in com
`GET /api/foods?search=arroz&remote=true`; sem `remote=true`, nenhuma quota externa é consumida.
Cada provider remoto usa `PROVIDER_TIMEOUT_SECONDS` (5 segundos por padrão); falhas são ignoradas para devolver resultados
parciais. Os resultados USDA são cacheados como alimentos globais porque CC0 permite cache
indefinido; por isso o TTL fica `NULL` para USDA (o parâmetro existe para fontes futuras como
FatSecret).
Para habilitar Open Food Facts e TBCA, use `FOOD_PROVIDER_SOURCES=usda,off,tbca` e configure
`OFF_USER_AGENT`. Use `GET /api/foods/barcode/{ean}` para consultar primeiro o cache local e,
quando necessário, o produto por código de barras no Open Food Facts. A busca por nome remota
também é explícita (`remote=true`) e nunca é usada como typeahead.
Para TBCA, cada busca remota consulta no máximo `TBCA_DETAIL_LIMIT` detalhes
(5 por padrão), com no máximo 3 requisições simultâneas e timeout de 2,5 segundos
por requisição; o timeout global usa `PROVIDER_TIMEOUT_SECONDS`.
Os alimentos carregam metadados como `source_version`, `attribution`, `barcode`, `locale`,
`fetched_at`, `expires_at`, `archived_at` e nutrientes extras; alimentos arquivados ou com
cache expirado ficam fora da busca sem invalidar entradas já registradas.

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
   escolha a região desejada e copie a conexão **pooled** (`-pooler`) exatamente como
   a Neon fornecer. O scheme e os parâmetros SSL são normalizados automaticamente.
2. No dashboard da Vercel, selecione **Add New... > Project**, importe este repositório
   do GitHub e deixe a Vercel detectar o preset **FastAPI** automaticamente. A Vercel
   serve `app/main.py:app`, usa o Python definido no `pyproject.toml` e instala as
   dependências a partir do `uv.lock`; não é necessário `vercel.json`.
   Em **Settings > Environment Variables**, adicione:
   - `DATABASE_URL`: URL pooled do Neon, que pode ser colada no formato original fornecido
     pela Neon; scheme e parâmetros SSL são normalizados automaticamente
   - `APP_ENV`: `production`
   - `DEFAULT_TIMEZONE`: por exemplo `America/Sao_Paulo`
   - `LOG_LEVEL`: `INFO`
   `SERVERLESS` não precisa ser configurada: é detectada automaticamente quando a Vercel
   define `VERCEL`.
3. Clique em **Deploy**. Para habilitar deploys automáticos a cada push, primeiro adicione
   a conexão do GitHub em **Vercel > Account Settings > Login Connections**. Sem essa conexão,
   `vercel git connect` falha com a mensagem de que é necessário adicionar uma Login
   Connection ao GitHub; depois disso, execute `vercel git connect` e selecione o projeto.
4. Para executar as migrações localmente contra o Neon:
   ```bash
   DATABASE_URL=<NEON_POOLED_DATABASE_URL> uv run alembic upgrade head
   ```
   A URL pooled do Neon funciona no formato original, graças à normalização automática.
5. Para o workflow `migrate.yml`, abra o GitHub em **Settings > Secrets and variables >
   Actions > New repository secret** e crie `DATABASE_URL` com a mesma URL pooled do Neon.
   Esse passo requer acesso do proprietário do repositório; o `gh` local não configura esse
   segredo sem autenticação.

## Autenticação OAuth 2.1

Além dos tokens bearer estáticos (mantidos para compatibilidade com a API REST e clientes
existentes), o servidor oferece um Authorization Server OAuth 2.1 com Dynamic Client
Registration (RFC 7591). Os metadados ficam em:

- `/.well-known/oauth-authorization-server`
- `/.well-known/oauth-protected-resource/mcp`

O fluxo usa authorization code com PKCE S256, tokens de acesso com duração de uma hora,
refresh tokens rotativos com duração de 30 dias e revogação em `/revoke`. Os escopos
aceitos são `mcp` e `ACCESS_VIEW_MANAGE_MCP_CONTENT`; este último é aceito apenas por
compatibilidade com clientes Google e não concede permissões adicionais.

No ambiente de desenvolvimento, `/oauth/login?pending=<id>&email=<email>` resolve um
usuário existente pelo e-mail (ou por `DEV_LOGIN_EMAIL`) e conclui a autorização. Esse
provedor é deliberadamente bloqueado em produção com HTTP 503. Quando
`GOOGLE_CLIENT_ID` e `GOOGLE_CLIENT_SECRET` estão configurados, o login usa Google OIDC:
o callback troca o código no Google e consulta o endpoint HTTPS `userinfo`, exigindo
`email_verified=true` sem validar JWT localmente. Usuários existentes são vinculados pelo
`google_sub` ou pelo e-mail, independentemente de `ALLOWED_EMAILS`; somente novas contas
precisam estar na allowlist. Em produção sem as credenciais Google, o login responde HTTP 503.

Para configurar o Google Cloud:

1. Em **Google Cloud Console > APIs & Services > Credentials**, crie um OAuth client do
   tipo **Web application**.
2. Adicione como redirect URI:
   `https://macro-tracker-alpha-six.vercel.app/oauth/google/callback`
3. Configure `GOOGLE_CLIENT_ID` e `GOOGLE_CLIENT_SECRET` na Vercel e `ALLOWED_EMAILS`
   com os e-mails autorizados a criar contas. Use os escopos `openid email`.
4. Mantenha `OAUTH_REQUIRE_CONSENT=true` para exibir a tela de autorização do Macro Tracker;
   desligue-o apenas durante depuração.

Após o login Google, a tela de consentimento mostra o nome do cliente MCP e descreve o
acesso a alimentos, registros, metas e resumos. **Autorizar** emite o código OAuth; **Cancelar**
retorna `access_denied` ao redirect URI original. A conta autenticada também pode ser consultada
e atualizada em `GET /api/me` e `PATCH /api/me` (este último aceita somente `timezone` IANA).
O consentimento é vinculado ao navegador que concluiu o login Google por meio de um cookie
seguro de curta duração; outro navegador não pode autorizar a pending.

## MCP

O endpoint remoto é `https://<seu-app>.vercel.app/mcp`. Clientes que suportam OAuth devem
usar o registro dinâmico e os metadados acima. O bearer token estático continua aceito:

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
100 g. A resposta de alimentos também inclui `source`, `source_ref` e `category`.
