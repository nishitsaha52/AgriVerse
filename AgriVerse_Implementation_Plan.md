# AgriVerse Production Implementation Plan

## Summary

Rebuild the non-functional CRA/Express/Flask prototype as a production application using:

- `apps/web`: Next.js 15, TypeScript strict, Tailwind, shadcn/ui, TanStack Query, and PWA support.
- `apps/api`: FastAPI, Pydantic v2, async persistence, deterministic agronomy, and AI/retrieval services.
- `packages/api-client`: generated TypeScript client from FastAPI OpenAPI.
- Postgres 17 + pgvector, Redis 7, and MinIO AIStor as the only platform-operated runtime services.
- OpenAI for vision/agent workloads and Voyage for embeddings/reranking.

The implementation covers the complete 10–13 week application scope. Billing, deployment, containers, infrastructure, observability infrastructure, and credential provisioning remain out of scope.

## Delivery Sequence

| Phase | Schedule | Exit milestone |
|---|---:|---|
| 0. Containment | Days 1–2 | Compromised key revoked, generated dependencies removed from Git, history sanitized |
| 1. Foundation | Weeks 1–3 | Monorepo, database, RLS, storage, CI, and auth working |
| 2. Core agronomy | Weeks 3–6 | Fields, soil, crop suitability, and weather usable without AI |
| 3. Scan diagnosis | Weeks 5–8 | A validated image produces a structured, cited diagnosis |
| 4. Retrieval | Weeks 7–11 | Confirmed-case and licensed-document retrieval operational |
| 5. Agronomist agent | Weeks 10–12 | Field-aware, tool-using multilingual advisory experience |
| 6. Hardening | Weeks 11–13 | Security, accessibility, evaluation, and load gates passing |

## Phase 0 — Containment

- Preserve the current worktree before cleanup: it already contains large user-owned `node_modules` deletions and two untracked design documents.
- Revoke the exposed OpenWeather key and remove `server/weather/.env`.
- Update `.gitignore` for nested `node_modules/`, `build/`, `.env`, Python caches, and generated clients.
- Remove the obsolete model downloader, legacy build output, and tracked dependency directories.
- Create a backup ref, run `git filter-repo`, verify the secret and generated files are absent from every ref, then coordinate the required force-push.
- Do not begin the rebuild until the containment commit and history rewrite are independently verified.

## Phase 1 — Foundation, Persistence, and Authentication

- Establish pnpm workspaces, Python dependency locking, strict TypeScript, strict mypy, Ruff, ESLint, pytest, and Playwright.
- Use SQLAlchemy 2 async plus Alembic instead of Prisma Client Python. The planned Python client was [archived in April 2025](https://github.com/RobertCraigie/prisma-client-py), making the documented SQLModel/Alembic fallback necessary; direct SQLAlchemy avoids an unnecessary wrapper.
- Create the ER model from the architecture document, including organizations, memberships, farms, fields, soil tests, recommendations, weather records, scans, diagnoses, embeddings, documents, feedback, reviews, usage records, and audit logs.
- Add implementation-required tables omitted from the ER diagram: organization invite, refresh session, agent conversation/message, and idempotency record.
- Store validated latitude/longitude, state, district, and derived agro-climatic zone rather than requiring PostGIS, which is not part of the pinned pgvector runtime.
- Carry `organization_id` directly on every tenant table. Set `app.org_id` with `SET LOCAL` for every transaction and enforce matching RLS policies.
- Implement MinIO per-organization object prefixes and presigned PUT/GET services.
- Spike BullMQ Python against Redis for priorities, retries, delayed work, deduplication, reconnect recovery, and graceful shutdown. BullMQ’s official documentation still describes Python support as [experimental](https://docs.bullmq.io/python/introduction); automatically adopt ARQ if any required behavior fails.
- Implement RFC 7807 errors, request IDs, JSON logs, health/readiness endpoints, and OpenAPI-to-TypeScript generation with a drift check.
- Implement phone+PIN farmer auth and configurable Google/Microsoft staff OAuth:
  - Six-digit-or-longer PIN, Argon2 hashing, E.164 normalization, and lockout after five failures.
  - Fifteen-minute access tokens; rotating 60-day farmer and 7-day staff refresh sessions.
  - Self-registration requires a single-use, expiring organization invite code.
  - Permission-based FastAPI dependencies enforce farmer, field-agent, agronomist, organization-admin, support, and super-admin access.
  - Field agents can onboard farmers and reset PINs; every reset is audited.

## Phase 2 — Fields, Deterministic Agronomy, and Weather

- Build organization-scoped farm and field CRUD, soil-test history, and current-crop management.
- Implement pure, versioned agronomy functions for:
  - Fertility index from N, P, K, pH, EC, OC, S, Zn, Fe, Cu, Mn, and B.
  - Rice, wheat, and tomato suitability ranking.
  - Deterministic weather-alert thresholds.
- Cite the agronomic source for every range, weight, and threshold. Persist calculated results with `algorithm_version` so historical recommendations remain auditable.
- Implement `WeatherProvider` with IMD as primary and Open-Meteo as fallback, normalized to one internal DTO.
- Cache current conditions for 10 minutes and forecasts for a longer provider-appropriate period, keyed by district/agro-climatic zone.
- Deliver farmer dashboard, field setup, soil-test form, recommendation view, and weather alerts.
- Ship English, Hindi, Bengali, Marathi, Telugu, and Tamil UI chrome; support approximately twelve configured languages for generated advice.
- Meet WCAG 2.1 AA fundamentals and design for low-end Android and intermittent connectivity.

## Phase 3 — Secure Scan Diagnosis

- Expose the asynchronous scan workflow:
  - `POST /api/v1/fields/{fieldId}/scans` returns `scan_id` and a short-lived presigned PUT.
  - `POST /api/v1/scans/{scanId}/complete` validates the uploaded object and schedules processing.
  - `GET /api/v1/scans/{scanId}` returns pending, processing, completed, rejected, or failed status.
  - `POST /api/v1/scans/{scanId}/feedback` records worked, failed, or unsure outcomes.
- Validate size at 10 MB or less, sniff magic-byte MIME, enforce a pixel cap, reject decompression bombs, strip EXIF, and re-encode with Pillow before any provider call.
- Compute SHA-256 after canonical re-encoding and reuse a tenant-safe cached diagnosis for identical images.
- Use an inexpensive image gate before diagnosis; non-plant, blurry, or dark images return the explicit non-diagnosable path.
- Use the OpenAI Responses API with image input, Pydantic-backed structured output, and stored request metadata. OpenAI currently recommends Responses for reasoning and tool workflows, and its current model family supports image input ([model guidance](https://developers.openai.com/api/docs/guides/latest-model), [model catalog](https://developers.openai.com/api/docs/models)).
- Seed configurable roles with `gpt-5.6-luna` for gating, `gpt-5.6-terra` for routine diagnosis, and `gpt-5.6-sol` for escalations/agent work; promote only snapshot IDs that pass the eval suite.
- Require primary condition, confidence band, observed evidence, up to three differential diagnoses, immediate actions, citations, and `requires_expert`.
- Never expose product names or dosages without a Tier 1 citation. When none is available, return generic active-ingredient guidance and expert referral.
- Record provider, model snapshot, prompt version, retrieved chunks, token use, cost estimate, and complete structured response.

## Phase 4 — Embeddings, Corpus, and Human Review

- Use 1024-dimensional vectors throughout. Adopt the current successors to the documents’ proposed Voyage models:
  - `voyage-multimodal-3.5` for scan images.
  - `voyage-4-large` for document and soil-summary text.
  - Both support a 1024 default dimension according to the official [multimodal](https://docs.voyageai.com/docs/multimodal-embeddings) and [text embedding](https://docs.voyageai.com/docs/embeddings) documentation.
- Add HNSW cosine indexes, organization indexes, and RLS. Over-fetch candidates before tenant filtering and truncation to prevent filtered ANN searches from under-returning.
- Permit `confirmed_dx IS NOT NULL` as the sole membership rule for similar-case retrieval.
- Build the prioritized agronomist queue using low confidence, no close neighbors, diagnosis/neighbor disagreement, negative feedback, and Tier 1 dosage usage.
- Only an agronomist confirmation or correction writes `confirmed_dx`; farmer feedback can enqueue review but never promote a scan.
- Implement licensed document ingestion:
  - Reject CC BY-NC material.
  - Require publisher, licence, source URL, retrieval date, authority tier, and applicable regions.
  - Parse, semantically chunk at roughly 512 tokens with 15% overlap, preserve page/section metadata, embed, retrieve about 50 candidates, and rerank to five.
  - Filter authority tier and region in SQL before reranking.
- Seed the retrieval/evaluation corpus with commercially usable field-condition images for rice, wheat, and tomato, followed by agronomist-reviewed production cases.

## Phase 5 — Agronomist Agent

- Add field-scoped conversations and messages with multilingual output and streaming responses.
- Expose typed tools for field details, latest soil test, scan history, forecast, fertility calculation, crop ranking, similar scans, and agronomy-document search.
- Re-authorize `field_id` and every resource identifier inside each tool using the caller’s organization context.
- Keep arithmetic and alert evaluation inside deterministic services; the model may retrieve and explain those results but may not recompute them.
- Treat retrieved documents and image-derived text as untrusted data, delimit it from instructions, and reject prompt-injection attempts.
- Deliver farmer chat plus the staff review console; defer the external AgriVerse MCP server until after the production core is accepted.

## Phase 6 — Application Hardening

- Apply a strict CSP, HSTS, secure headers, cookie protections, and an explicit CORS allowlist.
- Enforce per-user and per-organization rate limits and daily AI quotas before provider calls.
- Configure MinIO with private buckets, per-organization prefixes, server-side encryption, and presigned URLs valid for no more than five minutes.
- Record every data mutation and AI call in `AuditLog`, including actor, organization, provider, model, and request ID.
- Implement soft deletion, data export, and erasure workflows for DPDP compliance.
- Add dependency, container-image, static-analysis, and secret scanning to CI.
- Run k6 load tests and provide capacity baselines to the platform team.

## Public Interfaces and Contracts

- Prefix REST endpoints with `/api/v1`; use UUID identifiers, ISO-8601 timestamps, and RFC 7807 errors.
- Route groups: `auth`, `organizations`, `farms`, `fields`, `soil-tests`, `crop-recommendations`, `weather`, `scans`, `diagnoses`, `feedback`, `reviews`, `agronomist`, `documents`, `usage`, and `audit`.
- Keep `Diagnosis`, `FieldContext`, `Forecast`, `CropRanking`, `ReviewDecision`, and agent tool inputs as canonical Pydantic models.
- Generate the frontend client from OpenAPI; generated code is never manually edited.
- Require `Idempotency-Key` for scan completion, feedback, review decisions, and other retryable mutations.
- Return authoritative citation objects containing document, publisher, page, section, licence, URL, and authority tier—not unverified free-text citations.

## Test and Acceptance Plan

- Unit tests: at least 80% overall and 100% branch coverage for deterministic agronomy.
- Contract tests: generated client must exactly match the committed OpenAPI schema.
- Integration tests: Postgres/pgvector, Redis, and MinIO; prove ORM and raw-vector cross-organization access both fail.
- Auth tests: E.164 normalization, invite replay, PIN brute force, lockout/backoff, refresh rotation, reset auditing, and complete role/route matrix.
- Scan tests: oversized, spoofed, corrupt, decompression-bomb, duplicate, non-plant, blurry, and valid field images.
- Retrieval tests: Recall@5, regional filtering, authority-tier filtering, RLS/HNSW under-return behavior, and confirmed-only corpus access.
- AI evaluation gate: approximately 200 labelled field photos and 50 known-answer retrieval questions. Block changes that regress diagnosis accuracy, refusal behavior, or citation correctness.
- Safety tests: prompt-injected documents/images, absent Tier 1 dosage evidence, cross-tenant tool IDs, and negative farmer feedback.
- E2E tests: invite registration → field → soil test → recommendation → upload → cited diagnosis → feedback → agronomist review → agent follow-up.
- Hardening gates: CSP/HSTS/CORS, quota enforcement, five-minute presigned URL expiry, dependency/secret scanning, DPDP export/erasure, and k6 baseline results.

## Assumptions and Completion Criteria

- Farmer self-registration uses the selected organization invite-code model.
- Rice, wheat, and tomato are the only initial crop-specific diagnostic corpus; cotton is deferred.
- Pan-India support requires district/agro-climatic-zone retrieval filtering from the first release.
- An agronomist role will review roughly 5–10% of scans; without staffing, confirmed-image retrieval remains disabled and the product operates as a cited advisory system.
- AI and Voyage model IDs remain configuration values, but production uses immutable snapshots selected by the committed evaluation suite.
- Completion means all phase exit milestones and CI gates pass, the legacy services are no longer runtime dependencies, and the application operates only against the pinned Postgres, Redis, and MinIO interfaces plus configured AI/weather providers.
