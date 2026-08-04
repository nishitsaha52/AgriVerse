# AgriVerse

AgriVerse is a production-oriented field intelligence application for farmers,
field agents, and agronomists. It combines deterministic soil, crop, and weather
logic with cited image diagnosis, organization-isolated retrieval, and human
review.

The legacy CRA, Express, and Flask prototype is retained locally under
`recycle/legacy-prototype/` as recoverable migration history. It is excluded
from version control; the supported runtime is the new monorepo.

## Architecture

| Path | Purpose |
|---|---|
| `apps/web` | Next.js 15 farmer dashboard, scan flow, agent chat, and staff review console |
| `apps/api` | FastAPI REST API, ARQ worker, SQLAlchemy models, and Alembic migrations |
| `packages/api-client` | TypeScript types generated from the committed OpenAPI contract |
| `deploy` | OpenResty and systemd integration examples |
| `docs` | Production and centralized-infrastructure runbooks |

Runtime dependencies are Postgres 17 with pgvector, Redis, a private
S3-compatible MinIO bucket, an OpenAI-compatible endpoint (LiteLLM is
supported), Voyage embeddings/reranking, and configured weather providers.

## Implemented capabilities

- Organization-scoped farms and fields with PostgreSQL row-level security.
- Phone/PIN farmer enrollment using single-use invitations, E.164 normalization,
  Argon2 PIN hashing, progressive lockout, short access tokens, and rotating
  refresh sessions.
- Google and Microsoft staff OIDC with email-bound invitations and one-time
  exchange codes.
- Versioned deterministic fertility scoring, rice/wheat/tomato suitability, and
  weather alerts.
- Direct encrypted MinIO uploads, strict image validation/re-encoding, SHA-256
  duplicate reuse, asynchronous diagnosis, citation controls, feedback, and an
  agronomist confirmation queue.
- Voyage image/text vectors, pgvector HNSW indexes, region/tier filtering,
  reranking, confirmed-case retrieval, and licensed-document ingestion.
- Field-authorized agronomist chat with soil, weather, scan, and document
  context; multilingual answer configuration; prompt-injection screening.
- Usage records, immutable mutation/AI audit events, quotas, rate limits,
  idempotency records, privacy export/erasure, PWA shell, secure headers, and
  generated OpenAPI types.

## Local development

Requirements:

- Node.js 22 and Corepack
- pnpm 10.14
- Python 3.12–3.14
- uv
- Postgres with pgvector, Redis, and MinIO

Create configuration:

```bash
cp .env.example .env
```

Install and migrate:

```bash
corepack pnpm install --frozen-lockfile
uv sync --project apps/api --frozen
uv run --directory apps/api alembic upgrade head
```

Start the API, worker, and web application in separate terminals:

```bash
uv run --project apps/api uvicorn agriverse.main:app --app-dir apps/api --reload --port 8000
uv run --project apps/api arq agriverse.workers.WorkerSettings
corepack pnpm --filter @agriverse/web dev
```

The web app runs at `http://localhost:3000`; API documentation is available at
`http://localhost:8000/docs` outside production.

Bootstrap is allowed only on an empty database:

```bash
uv run --project apps/api python -m agriverse.cli bootstrap \
  --name "Demo cooperative" --phone "+919876543210" --pin "123456" \
  --email "admin@example.com"
```

## Verification

```bash
uv run --project apps/api ruff check apps/api
uv run --project apps/api mypy apps/api/agriverse
uv run --project apps/api pytest apps/api/tests --cov=agriverse
corepack pnpm lint
corepack pnpm typecheck
corepack pnpm test
corepack pnpm build
corepack pnpm test:e2e
```

Regenerate and verify the API contract:

```bash
uv run --project apps/api python apps/api/scripts/export_openapi.py
corepack pnpm --filter @agriverse/api-client generate
git diff --exit-code -- apps/api/openapi.json packages/api-client/src/generated/schema.d.ts
```

Production wiring for the already deployed centralized stack is documented in
[docs/CENTRALIZED_INFRASTRUCTURE.md](docs/CENTRALIZED_INFRASTRUCTURE.md).

## Security notes

Never commit `.env` files, access keys, OAuth secrets, AI provider keys, or
database credentials. Production startup rejects weak JWT/OAuth session
secrets. Use a non-superuser Postgres runtime identity without `BYPASSRLS`, keep
MinIO buckets private, and expose only OpenResty publicly.
