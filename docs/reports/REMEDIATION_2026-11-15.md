# Integration remediation — 15 November 2026

This follows the [initial live integration report](LIVE_INTEGRATION_TEST_2026-11-15.md).
The API, web app, and ARQ worker are running locally. API readiness returns HTTP
200 with database, queue, and storage connectivity available. Readiness confirms
bucket access; encrypted image writes still have the server-side blocker below.

## Completed actions

| Action | Change and verification |
|---|---|
| Retrieval migration | Ran Alembic upgrade and verified revision `20261115_0002`. All seven provider-specific columns are present; pgvector is `0.8.7`. |
| Reindex | Ran `reindex-embeddings`: **0 records, 0 failures**. There are no existing scan/document embeddings to rebuild. A new live Gemini query embedding successfully passed through both document and tenant-scoped scan pgvector search using the runtime role; both returned the expected empty results. |
| Runtime database role | Created `agriverse_runtime` without superuser, `BYPASSRLS`, schema CREATE, or database ownership. Granted table DML, sequence access, and read-only migration-version visibility. Updated private `.env` with generated runtime credentials and a separate migration URL. Tenant checks returned 1 membership with the correct context and 0 with no/wrong context. |
| Expired OpenAI key | Cleared the expired `OPENAI_API_KEY` locally and preserved the Gemini key. All configured Gemini application paths passed inference/schema tests, including both 1,024-dimensional retrieval embedding modes. No replacement OpenAI key was invented or requested in chat. |
| Certificate trust | Added verified OS trust for HTTPX, Authlib, OpenAI/Gemini clients, S3 clients, and OTLP exporters. An optional `TLS_CA_BUNDLE` adds organization CA roots. Certificate and hostname validation remain enabled. Actual Authlib discovery and Langfuse export/readback now pass with these application settings. |
| Keycloak issuer | Updated private `.env` to `https://wisdom-dev.local/keycloak/realms/agriverse`. Actual Authlib discovery passes, issuer matches exactly, and there is no redirect. Signing keys and S256 authorization/client/callback checks pass. Interactive-session evidence is described separately below. |
| Weather timestamps | Local provider times now use `utc_offset_seconds` before normalization to UTC. Current and hourly timestamps are corrected; the cache namespace advanced to v2 to avoid previously mislabelled cached values. Live Kolkata forecast drift is **0 seconds**. |
| Automatic Langfuse tracing | Added direct, optional LLM tracing independent of the OTel collector. Generation and embedding calls now create spans; metadata includes provider, model, task, status, timing, and available token counts. Prompts, answers, images, field data, credentials, and exception messages are excluded. A real application Gemini answer automatically exported a trace, and v2 readback returned its `GENERATION` observation. |
| Local services | Started API at `http://localhost:8000`, web at `http://localhost:3001`, and the ARQ worker as hidden background processes. API `/healthz` and `/readyz` and the web login page return HTTP 200. Process IDs and redirected logs are in ignored `.runtime/`. |
| Session rotation | Live session testing exposed an immediate foreign-key failure when a previous refresh session pointed at a pending replacement row. The replacement is now flushed before linking, within the same transaction. Repeated staff PIN login, authenticated farm query, and refresh returned HTTP 200; logout returned 204 and revoked the diagnostic session. |
| OTel | Traces, metrics, logs, and the Python SDK exporter passed live export again. CA trust also applies to HTTPS exporters. Optional instrumentation setup remains non-blocking; strict typing/import issues in the observability module were corrected. |

## MinIO routing repaired; encryption remains blocked

The original public URL was the console: the live OpenResty `/minio/` rule
forwards to port **9001**. The console and existing services remain available.

Installed [the bucket API snippet](../../deploy/openresty/agriverse-minio-api.inc)
into the existing TLS server through the existing MinIO include. It sends the
exact `/agriverse` bucket and `/agriverse/...` object paths to `minio:9000` without
rewriting the signed URI or Host. OpenResty syntax validation and reload passed.
Its existing worker-connection/file-limit warning was non-fatal; limits were not
changed as part of this routing fix.

The application's private `.env` now uses:

```dotenv
S3_ENDPOINT_URL=http://localhost:9000
S3_PUBLIC_ENDPOINT_URL=https://wisdom-dev.local
```

Public signed GET returned **200** and the exact 884 fixture bytes; browser CORS
preflight returned **204** for `http://localhost:3001`. These checks used a
temporary unencrypted diagnostic object. All reserved test object paths were
deleted and absence verified. Application writes still require AES256.

The former routing error **400 InvalidArgument** is resolved. Encrypted internal
and public PUT requests now both return **405 `XMinioPaidTierLicenseRequired`**.
The running image is AIStor
`RELEASE.2026-09-19T17-05-25Z.hotfix.4ef74f03d6f2`. MinIO documents encryption as
unavailable on its [Free license](https://docs.min.io/aistor/operations/licenses/).
Completing encrypted uploads requires an encryption-enabled license and server
configuration, or another AES256-capable S3 service. The requested license/endpoint
choice is pending; no license purchase, license bypass, downgrade, container
replacement, or removal of the application's encryption requirement was attempted.

Live infrastructure files:

- `/home/wisdom/Infra-native/openresty/conf.d/apps/21-agriverse-minio-api.inc`
- Existing `09-minio.inc` now includes that snippet.
- Before-edit backup:
  `/home/wisdom/Infra-native/openresty/conf.d/apps/09-minio.inc.agriverse-1794731483.bak`

For a different bucket name, update the two bucket location rules as well as
`S3_BUCKET`. A dedicated S3 hostname at its root is another supported deployment
layout. See MinIO's [NGINX guidance](https://min.io/docs/minio/linux/integrations/setup-nginx-proxy-with-minio.html)
on preserving the S3 API path and avoiding an added subpath prefix.

## Interactive Keycloak verification

The user confirmed reaching the AgriVerse dashboard at localhost:3001. A follow-up
read-only database check did not find a Keycloak-linked account or active Keycloak
session, and the running application had not recorded an OAuth callback at that
point. The only existing account still used the phone provider. Dashboard access
is user-confirmed, but its specific OIDC path is therefore **not independently
verified**. Direct staff PIN authentication and session rotation were separately
verified live. No Keycloak accounts, provider settings, passwords, or access roles
were changed by these checks.

The application sign-in link is:

<http://localhost:3001/login?organization_id=1ddd9e8a-13d9-427a-91e8-9a0f7a1c4dc3>

Choose **Continue with Keycloak** under **Staff sign-in**. This is separate from
the main phone/PIN form and the Keycloak administration console. Use the
`agriverse` realm user whose verified email matches an authorized AgriVerse staff
account. The [Keycloak setup guide](../KEYCLOAK_SETUP.md) now uses the correct
HTTPS issuer and covers user/email verification. The normal web OAuth start route
returns HTTP 307 toward the API; provider discovery and callback registration pass.

## Validation and evidence

- **103 API tests passed**, 2 infrastructure tests deselected. Existing destructive
  infrastructure tests were not run against the user's services.
- After the live refresh-rotation fix, all **18 authentication tests passed**
  again, as did the real PostgreSQL-backed session lifecycle.
- Ruff passed across `apps/api`; strict mypy passed using the API configuration.
- Updated regression tests cover weather timestamp normalization and cache
  invalidation, TLS verification, optional tracing, token metadata, and exclusion
  of private prompts/answers/exception messages from LLM spans.
- [Main follow-up checks](live-after-remediation-2026-11-15.json): Gemini, weather,
  OTel, automatic Langfuse tracing, MinIO routing, and provider discovery.
- [Readiness repeat](live-after-remediation-2026-11-15-readiness.json): database,
  Redis, API, web, and Keycloak. This supersedes the main run's database/Redis
  timeouts and first web compile timeout. The runner now imports provider modules
  before scheduling sockets and allows time for a cold web compilation.
- [Storage repeat](live-after-remediation-2026-11-15-storage.json): signed public
  download, byte integrity, CORS, cleanup, and the remaining license error.
- [Interactive OIDC follow-up](live-after-remediation-2026-11-15-oidc.json).
- [Verified PIN session lifecycle](live-after-remediation-2026-11-15-pin.json).

Google and Microsoft remain unconfigured and optional. OTel downstream dashboard
persistence was not queried. Actual LLM calls used only synthetic diagnostic
content; tracing metadata remains in the configured observability services.
Runtime credentials, migration credentials, CA private keys, provider keys,
authentication tokens, signed URLs, and private identity details are omitted from
these reports.
