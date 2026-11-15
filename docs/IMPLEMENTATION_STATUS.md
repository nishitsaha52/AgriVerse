# Implementation status

Updated: 2026-11-15

## Delivered

- Monorepo foundation, pinned pnpm and uv lockfiles, strict TypeScript/mypy,
  Ruff/ESLint, CI, contract generation, unit tests, Playwright, and opt-in
  infrastructure integration tests.
- FastAPI application, Postgres/pgvector schema, Alembic migration, tenant RLS,
  Redis/ARQ worker, private MinIO storage, RFC 7807 errors, request IDs, JSON
  logging, health/readiness, OpenTelemetry, secure headers, rate limits, quotas,
  idempotency, usage, and audit records.
- Farmer invitation/phone/PIN authentication, progressive lockout, rotating
  refresh sessions with replay response, logout revocation, field-agent PIN
  reset auditing, and Keycloak/Google/Microsoft staff OIDC.
- Optional staff OIDC in all environments; production phone/PIN staff access
  preserves membership, active-account, and lockout checks, with an explicit
  `STAFF_PIN_LOGIN_ENABLED` switch for OIDC-only deployments.
- Farm/field CRUD with soft deletion; soil history, sourced/versioned fertility
  and crop rankings; Open-Meteo weather normalization and application-generated alerts.
- Safe asynchronous image upload and processing, structured/cited diagnosis,
  duplicate reuse, retrieval, dosage controls, feedback, prioritized human
  review, and confirmed-only case promotion.
- Licensed document ingestion, semantic chunking, separate 1024-dimensional OpenAI/Gemini
  embeddings, pgvector HNSW search, SQL region/tier filtering, reranking, and
  prompt-injection screening.
- Farmer dashboard, field setup, soil workflow, weather, scan polling,
  diagnosis, feedback, agent chat, staff review console, staff OAuth, PWA shell,
  mobile smoke test, accessibility-oriented semantics, and secure BFF cookies.
- Centralized `wisdom` infrastructure mapping, OpenResty config, and hardened
  systemd unit examples.

## Verified locally

- Ruff formatting and lint.
- Strict mypy.
- 99 API tests passing with 86.81% coverage; 2 infrastructure tests require explicit opt-in.
- Web TypeScript and ESLint.
- Vitest (11 tests).
- Next.js production build.
- Playwright Pixel 7 smoke journeys (3 tests), including the Keycloak redirect.
- Deterministic OpenAPI and generated TypeScript schema.

## Rollout gates requiring the production environment

These are operational acceptance gates rather than missing application code:

1. Run the integration tests against a disposable database/Redis/MinIO namespace
   on `wisdom`; never point destructive test fixtures at production data.
2. Configure MinIO browser CORS and its public TLS S3 endpoint.
3. Populate environment secrets, direct OpenAI/Gemini API keys, provider OIDC
   redirect URIs, and the Open-Meteo configuration. Apply the provider
   embedding migration and run explicit reindexing for existing retrieval data.
4. Verify Langfuse trace delivery through a configured collector route or direct
   exporter. The dashboard URL is `https://wisdom-dev.local/langfuse/`; setting
   the URL and project keys alone does not wire ingestion.
5. Obtain and record agronomist approval for the v1 index weights. Government
   and TNAU threshold sources are embedded and returned by the API, but a human
   domain owner must approve production advisory policy.
6. Ingest only reviewed, commercially permitted agronomy documents and licensed
   rice/wheat/tomato image data. The application intentionally ships no
   unverified diagnosis corpus.
7. Run the labelled 200-image/50-question evaluation gate with that corpus and
   execute `tests/load/k6-smoke.js` on the target capacity. Record the resulting
   model snapshots and platform baseline.
8. Revoke any real key discovered by secret scanning. The tracked legacy weather
   value inspected in this checkout is a placeholder, but the repository history
   should still be scanned before release.
9. Coordinate any Git history rewrite and force-push with all collaborators.
   Generated dependencies have been removed from the Git index while remaining
   available on the local filesystem.

Production traffic should not be enabled until these gates are signed off.
