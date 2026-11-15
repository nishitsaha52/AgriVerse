# Live integration test results — 15 November 2026

This records the initial state. See [subsequent remediation results](REMEDIATION_2026-11-15.md)
for the fixes and follow-up live tests.

The configured services were tested from the AgriVerse development computer with
the application's actual `.env` settings and Python environment. The main run
started at **13:35 IST (08:05 UTC)**, with follow-up diagnostics afterward.
OTel, Langfuse, and configured OIDC checks were explicitly authorized before testing.

**Gemini generation and embeddings work, including fallback from the expired
OpenAI key. The whole application is not ready for end-to-end use:** the live
database is behind the code's retrieval schema, MinIO's application upload paths
fail, and the API/web processes are not listening.

## Results

| Integration | Status | Live evidence and limits |
|---|---|---|
| PostgreSQL authentication/query | Pass | Connected to `agriverse`; `SELECT 1` returned `1` in a read-only transaction. pgvector `0.8.7` is installed. |
| PostgreSQL application schema | Fail | Database revision is `20260731_0001`; code requires `20261115_0002`. Seven provider-embedding columns are absent. Runtime role also has superuser and `BYPASSRLS` privileges. |
| Redis | Pass | Authenticated PING, unique-key SET with expiration, GET equality, TTL check, DELETE, and verification that the key was gone. |
| MinIO basic storage | Pass | Signed bucket access and a temporary 884-byte JPEG PUT/HEAD/GET succeeded through `http://localhost:9000`; bytes matched exactly. |
| MinIO application encryption | Fail | AES256 upload, as required by the application, returned HTTP **405**, code **`XMinioPaidTierLicenseRequired`**. |
| MinIO public uploads/CORS | Fail | The configured public URL `https://wisdom-dev.local/minio` returned HTTP **400**, code **`InvalidArgument`**, message **“S3 API Requests must be made to API port.”** Presigned PUT and browser OPTIONS fail. Download after that PUT could not be exercised. Default Python TLS trust also rejects the internal certificate. |
| OpenAI | Fail | Real inference and embedding requests both returned HTTP **401**, code **`expired_secret_key`**, type `invalid_request_error`. Its configured models' capabilities could not be verified with this key. |
| Gemini | Pass | Real application structured answer, image gate, image description, diagnosis schema, and reranking succeeded using `gemini-3.8-flash`. Document and query embeddings succeeded using `gemini-embedding-001`, each with 1,024 finite, normalized dimensions. |
| OpenAI → Gemini fallback | Pass | With both real keys configured, application answer and retrieval-query embedding logged OpenAI authentication failures and completed successfully with Gemini. This verifies provider fallback; database-backed retrieval is still blocked by the missing migration. |
| Open-Meteo connectivity/data | Pass | Forecast HTTP 200; current conditions and all four requested hourly arrays contain valid values across 72 hours. Application adapter also returned 72 forecast points. |
| Open-Meteo timestamp integrity | Fail | Kolkata response uses `Asia/Kolkata`, offset **19,800 seconds**. The adapter labels naive local timestamps as UTC, producing a **5h30m** timestamp error. |
| OTel | Pass, receiver/exporter scope | Valid OTLP/protobuf traces, metrics, and logs each returned HTTP **200**, with zero reported rejections. The application's Python `OTLPSpanExporter` also returned **`SUCCESS`**. Downstream Tempo/Prometheus/Loki storage and dashboards were not queried. |
| Langfuse service/authentication | Pass with Windows trust | Health HTTP **200**, version **4.50.0**. Configured project API keys authenticated successfully, with one accessible project. Default Python certificate trust fails; a verified SSL context using Windows trusted roots succeeds. |
| Langfuse ingestion/readback | Pass with Windows trust | Direct synthetic generation OTLP POST returned **200**. Current **v2 observations API** returned the same trace ID and one **`GENERATION`** observation. Legacy trace/observation readback routes returned **404**; those errors do not mean the trace was lost. |
| Langfuse automatic application tracing | Incomplete | Application source declares `LANGFUSE_*` settings but does not consume them in an exporter or instrument LLM calls for Langfuse. The successful test used a direct diagnostic export; automatic application LLM tracing was not demonstrated. An external collector route, if present, was not inspected. |
| Keycloak discovery/client setup | Partial | HTTPS discovery and JWKS returned **200** with Windows certificate trust. Two signing keys were returned; S256 PKCE is advertised. Authorization returned the login form for client `agriverse-web` and the exact API callback, demonstrating client/redirect acceptance. |
| Keycloak application sign-in | Blocked | Configured HTTP discovery returns **301**, which the actual Authlib discovery call rejects. Advertised issuer is HTTPS. HTTPS discovery with default Python trust fails certificate validation. API/web endpoints are not listening. User sign-in, token exchange/validation, account linking, and session creation were not completed. |
| Google OIDC | Not configured | No client ID configured; no provider flow was attempted. |
| Microsoft Entra ID OIDC | Not configured | No client ID configured; no provider flow was attempted. |
| API/web | Not running | Connections to `http://localhost:8000/healthz` and `http://localhost:3001/login` failed. Service-level checks used live dependencies directly and application service adapters where stated. |

## Actions needed before full application testing

1. Apply the pending migration to the intended database:

   ```powershell
   uv run --directory apps/api alembic upgrade head
   ```

   The missing fields are `embedding_model`, `gemini_embedding`, and
   `gemini_embedding_model` on both `scan_embedding` and
   `agronomy_document_chunk`, plus `scan_embedding.embedding_text`. Migration
   alone does not re-embed existing data; existing retrieval content needs the
   documented provider-specific reindex step. No migration or reindex was run
   during these read-only database diagnostics.

2. Set `S3_PUBLIC_ENDPOINT_URL` to a browser-reachable **S3 API** endpoint.
   The current route reports an API-port error. Validate signed uploads,
   downloads, and CORS after correcting the reverse-proxy route. Resolve the
   server's rejected AES256 operation while preserving the application's
   encryption requirement; basic unencrypted storage success does not resolve
   application uploads. No storage security settings were changed.

3. Replace the expired OpenAI key if OpenAI should be used. Gemini-only operation
   and fallback both passed provider-level tests. Removing the invalid OpenAI
   value avoids a rejected OpenAI call before each fallback. Retrieval still
   requires the updated database schema and compatible provider embeddings.

4. Configure certificate trust for Python clients using the organization's CA
   chain. Diagnostic Windows-root SSL contexts verified certificates successfully;
   TLS verification was never disabled. That diagnostic context does not change
   application HTTP-client settings.

5. Set Keycloak's issuer to the exact discovery value:

   ```dotenv
   KEYCLOAK_ISSUER_URL=https://wisdom-dev.local/keycloak/realms/agriverse
   ```

   Keep the accepted callback:
   `http://localhost:8000/api/v1/auth/staff/oauth/keycloak/callback`.
   Resolve Python TLS trust, start API/web, and complete a staff sign-in with
   a verified-email Keycloak user authorized in AgriVerse. See
   [Keycloak setup](../KEYCLOAK_SETUP.md). No identity-provider settings or
   accounts were changed.

6. Connect actual application LLM spans to Langfuse using a direct exporter or
   an appropriate collector route, then verify a real application request in
   the dashboard. Service authentication and diagnostic trace storage already
   passed. For readback, use the current
   [v2 observations API](https://langfuse.com/faq/all/export-single-trace-or-session);
   the [API migration guide](https://langfuse.com/faq/all/deprecated-api-migration)
   documents the legacy routes.

7. Correct weather timestamp normalization to respect `utc_offset_seconds` or
   request UTC timestamps. Use a non-superuser application database role without
   `BYPASSRLS` so tenant row-level security applies to runtime queries.

## Changes and cleanup

- No application configuration, database records/schema, bucket settings,
  identity-provider accounts, or provider keys were changed by testing.
- The unique Redis test key and all six reserved MinIO test object paths across
  the main and follow-up runs were deleted; absence was checked afterward.
- Small real provider requests were made; Gemini successfully processed the
  synthetic text/image fixtures. These tests verify integration and schema
  compatibility, not diagnosis quality on real crops.
- OTel diagnostic telemetry and one Langfuse synthetic generation observation
  were intentionally exported. Langfuse trace ID:
  `2388419fd604b9136c8f7fda0ba0a41f`.
- Reports contain no API keys, passwords, authorization headers, presigned URLs,
  OAuth tokens, or private user/field content.

## Evidence and repeatable checks

- [Main sanitized results](live-connectivity-2026-11-15.json)
- [MinIO/Keycloak follow-up results](live-connectivity-2026-11-15-followup.json)
- [OTel SDK/protocol results](live-connectivity-2026-11-15-otel.json)
- [Diagnostic runner](../../apps/api/scripts/live_connectivity_check.py)

Run from the repository root; this uses the normal `.env` and makes small real
LLM requests. Optional integrations are tested only with their explicit flags:

```powershell
uv run --project apps/api python apps/api/scripts/live_connectivity_check.py
uv run --project apps/api python apps/api/scripts/live_connectivity_check.py --otel --langfuse --oidc
```

Use `--only` for selected services, such as `--only MinIO OIDC --oidc`.
Reports receive timestamped names by default; `--output` sets an explicit path.
The runner checks Keycloak discovery and authorization-page acceptance, not an
interactive user sign-in. Future configured Google/Microsoft providers still
need their own interactive flow tests. Automatic application Langfuse tracing
also needs a separate instrumented request. Ruff lint and formatting checks
passed for the added runner.
