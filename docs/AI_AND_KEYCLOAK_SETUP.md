# Direct AI providers and development Keycloak

## API keys

Set these server-side values in the repository root `.env`:

```dotenv
OPENAI_API_KEY=your-openai-api-key
GEMINI_API_KEY=your-gemini-api-key
```

OpenAI is primary for plant-image checks, diagnosis, assistant answers, image
descriptions, document reranking, and embeddings. Gemini is optional fallback
when OpenAI is unavailable or returns an invalid response. Gemini-only operation
also works if only its key is configured. Provider refusals do not trigger a
second provider. API keys never use `NEXT_PUBLIC_` names.

Both providers are called at their direct HTTPS endpoints. No inference gateway
or external secret manager is required. Production systemd services can read
`/etc/agriverse/agriverse.env` through their existing `EnvironmentFile` setting.

Model IDs are configurable with `OPENAI_{GATE,VISION,AGENT,RERANK,EMBEDDING}_MODEL`
and `GEMINI_{GATE,VISION,AGENT,RERANK,EMBEDDING}_MODEL`; see `.env.example` for the
individual variables. `AI_TIMEOUT_SECONDS` bounds each provider request. The
default Gemini generation model is `gemini-3.8-flash`.

## Retrieval migration and fallback

OpenAI embeddings accept text. Scan similarity therefore uses a factual visual
description generated from the normalized image, then embeds that description.
This replaces direct image embeddings; it is description similarity rather than
pixel-level similarity. Human confirmation still controls which prior cases
enter the retrieval corpus.

OpenAI and Gemini vectors have separate columns and model labels. Queries use
only vectors from the matching provider and model. Equal vector dimensions do
not make different models compatible. During ingestion, when both keys are
configured, the same text is embedded by both providers to prepare the fallback
corpus. This incurs embedding requests to both providers. If only one succeeds,
ingestion can continue with that provider. Queries prefer OpenAI and fall back
to Gemini on provider failure or an empty primary corpus. Reranking uses the
same generation fallback; if it is unavailable, the vector ordering is kept.

The default `VECTOR_DIMENSION=1024` preserves the existing database vector size.
Do not change it against an existing schema without a separate schema migration
and complete reindex. Vectors are dimension-checked, checked for finite values,
and normalized. Legacy vectors stay in place but have no matching provider label,
so they are excluded until explicitly reindexed.

Stop the API/worker before syncing packages on Windows if a DLL is in use. From
the repository root:

```powershell
uv sync --project apps/api --frozen
uv run --directory apps/api alembic upgrade head
uv run --project apps/api python -m agriverse.cli reindex-embeddings
```

Run reindexing after adding a fallback key or changing an embedding model. It
processes document chunks and completed scans, preserves human confirmations,
skips records already current for all configured providers, and can be rerun
after failures. It makes real embedding calls and may describe old scan images
through the vision model, so provider charges apply. Schema migration itself
makes no AI calls and does not erase old vectors. Reindexing is not automatic.
After reindexing, schema downgrade is refused because it cannot restore the old
vector space. Rollback of indexed data requires a pre-migration database backup.

Optional controls:

```powershell
uv run --project apps/api python -m agriverse.cli reindex-embeddings --batch-size 16 --organization-id YOUR_ORGANIZATION_UUID
```

The organization filter limits scans; document chunks form the shared reviewed
corpus and are still reindexed. Use the database identity that can read all
intended organizations, or pass one organization explicitly. If a provider fails,
available embeddings are committed, missing provider vectors remain eligible for
retry, and the command exits unsuccessfully until all requested records complete.

## Configure development Keycloak

Follow the dedicated [Keycloak setup guide](KEYCLOAK_SETUP.md) for realm/client
creation, capability settings, callback URLs, verified users, issuer discovery,
root `.env` configuration, and troubleshooting. It includes the
`wisdom-dev.local/keycloak` deployment example.

Keycloak fields can stay blank in development or production. Staff/admin PIN
login is enabled by default (`STAFF_PIN_LOGIN_ENABLED=true`); unconfigured OIDC
providers have no sign-in button. Set the flag to `false` in API and web
environments if you prefer OIDC-only staff access. PIN login requires a registered
phone and PIN, which bootstrap provisions for the initial organization admin.

## Provider references

Implementation verification: 99 API tests passed with 86.81% coverage, 11 frontend
unit tests and 3 browser tests passed, and the production web build passed.
Provider and OIDC responses were mocked; live credentials, the new migration on
your database, and your future Keycloak realm have not been exercised. The existing
observability import issue still affects full API mypy checks.

- [OpenAI embeddings and dimensions](https://developers.openai.com/api/docs/guides/embeddings)
- [Gemini OpenAI SDK compatibility for structured generation](https://ai.google.dev/gemini-api/docs/openai)
- [Gemini native embedding API](https://ai.google.dev/api/embeddings)
- [Gemini 3.8 Flash capabilities](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)
- [Keycloak discovery and Authorization Code flow](https://www.keycloak.org/securing-apps/oidc-layers)
