# Implementation status

Updated: 2026-07-31

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
  reset auditing, and Google/Microsoft staff OIDC.
- Farm/field CRUD with soft deletion; soil history, sourced/versioned fertility
  and crop rankings; IMD-gateway/Open-Meteo weather normalization and alerts.
- Safe asynchronous image upload and processing, structured/cited diagnosis,
  duplicate reuse, retrieval, dosage controls, feedback, prioritized human
  review, and confirmed-only case promotion.
- Licensed document ingestion, semantic chunking, 1024-dimensional Voyage
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
- 47 API tests passing, 2 infrastructure tests skipped without explicit
  infrastructure opt-in, and 85% application coverage.
- Web TypeScript and ESLint.
- Vitest.
- Next.js production build.
- Playwright Pixel 7 smoke journey.
- Deterministic OpenAPI and generated TypeScript schema.

## Rollout gates requiring the production environment

These are operational acceptance gates rather than missing application code:

1. Run the integration tests against a disposable database/Redis/MinIO namespace
   on `wisdom`; never point destructive test fixtures at production data.
2. Configure MinIO browser CORS and its public TLS S3 endpoint.
3. Populate Infisical values, provider OIDC redirect URIs, LiteLLM aliases,
   Voyage credentials, and the normalized IMD gateway contract.
4. Resolve the currently unhealthy `langfuse-web` service before making
   Langfuse a required telemetry destination.
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
