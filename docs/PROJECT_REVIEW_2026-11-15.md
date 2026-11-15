# AgriVerse project review — 15 November 2026

## Scope and architecture

Reviewed the supported monorepo's configuration and startup scripts, API routes,
authentication and tenant permissions, schema/migrations, web login and API proxy,
scan processing, retrieval/storage/provider integrations, deployment examples,
documentation, and verification setup. The archived `recycle/` prototype is not
part of the supported application. This review does not certify a production
deployment or external AI-provider behavior.

| Component | Responsibility |
|---|---|
| `apps/web` | Next.js application and same-origin API proxy; session tokens stay in HTTP-only cookies |
| `apps/api` | FastAPI, phone/PIN and staff OAuth, organization permissions, agronomy, scans, and chat |
| API worker | ARQ jobs for image validation, embeddings, diagnosis, and review routing |
| Postgres/pgvector | Application state, tenant row-level security, and retrieval vectors |
| Redis | Jobs, quotas, cache, and single-use OAuth exchanges |
| MinIO | Private source/canonical images and presigned uploads |
| External providers | Direct OpenAI with Gemini fallback for inference/retrieval, and weather |
| `packages/api-client` | Generated OpenAPI TypeScript contract |
| `deploy` | OpenResty ingress and separate systemd services |

## Issues corrected in this change

| Finding | Resolution |
|---|---|
| AgriVerse and Langfuse both defaulted to port 3000 | Web dev/start default to 3001; Langfuse is accessed through `https://wisdom-dev.local/langfuse/` |
| Root `.env` did not reach the web scripts | A shared launcher loads it before Next selects its port or reads server configuration |
| API dotenv paths depended on the current directory | Root dotenv path is resolved from the configuration module; working-directory dotenv and process overrides remain available |
| CORS/origin/callback settings disagreed with the web port | Development defaults, example configuration, and local dotenv now use 3001 |
| Bootstrap required credentials on the command line | `BOOTSTRAP_NAME`, `BOOTSTRAP_PHONE`, `BOOTSTRAP_PIN`, and optional `BOOTSTRAP_EMAIL` supply defaults; explicit CLI flags override them |
| Bootstrap accepted PINs that login would reject | Require 6–12 digits before opening a database session; keep leading zeroes and hash before storage |
| Bootstrap admin could not use the farmer login endpoint | Login offers staff/admin PIN sign-in in all environments; bootstrap prints an organization-specific sign-in link |
| Staff PIN login lacked farmer-login account protections | Reject inactive/locked accounts, record failed attempts, and reset counters after successful login |
| Production CSP settings blocked development eval/hot reload and upgraded local HTTP | Development-only eval/WebSocket/HTTP allowances; HTTPS upgrade remains for production builds |
| Root scripts failed when pnpm was available only through Corepack | Nested workspace commands now use `corepack pnpm` |
| Next build could not resolve a transitive ESLint plugin in pnpm's store | FlatCompat explicitly resolves plugins beside `eslint-config-next` |
| Bootstrap docs used Bash continuation syntax and an invalid nonnumeric production PIN example | Document a single-line command and environment-based credentials |

The initial organization and user UUIDs remain database-generated. The login ID
is the phone number, and the password is its numeric PIN. Changing bootstrap
environment values does not update an existing account. The existing refusal
to bootstrap a database containing an organization remains intact. Staff PIN
login is available in development and production when `STAFF_PIN_LOGIN_ENABLED`
is true (the default). OIDC remains optional; setting the flag false disables
staff PIN login without removing any configured OIDC provider.

Next documents that its own dotenv loading happens too late to select the server
port. The launcher loads shared configuration first and passes an explicit port,
which also prevents automatic fallback to an origin that disagrees with CORS or
OAuth settings. See [Next CLI documentation](https://nextjs.org/docs/app/api-reference/cli/next).

## Remaining findings

These are findings from existing code, outside the requested port/bootstrap
change. The already-modified `agriverse/observability.py` was preserved.

| Priority | Finding and evidence | Follow-up |
|---|---|---|
| High | Full API lint reports 13 issues in `observability.py`; mypy reports the missing `opentelemetry.instrumentation.logging` module | Reconcile the existing telemetry edits with installed dependencies and CI checks |
| High | Account erasure in `routers/operations.py` clears phone/OAuth/PIN but retains `User.email` and conversation content | Define retained records explicitly and complete anonymization/deletion for personal content |
| Medium | `LANGFUSE_*` values are declared in settings but are not consumed by tracing code | Configure a collector route or implement direct Langfuse export before expecting Langfuse traces |
| Medium | Current telemetry setup labels the environment `development`, and its worker decorator is unused | Use the configured environment and wire worker initialization/task instrumentation; unset endpoints now disable export, and optional setup failures are contained |
| Medium | `enforce_request_limits` is called through AI quota enforcement; ordinary CRUD/auth routes do not use that general Redis limit | Apply intended per-user/per-organization limits consistently; PIN failure lockout alone is a separate control |
| Medium | Initial Alembic migration uses live `Base.metadata.create_all` | Freeze migration definitions so future model changes do not alter the historical migration |

## Verification boundaries

Validation completed: 99 API tests, 6 web unit tests, and 3 mobile browser tests
passed. Web ESLint, TypeScript, and the production build passed. Ruff formatting
and lint passed for all changed Python files; full API Ruff/mypy remain blocked
by the existing observability findings above. The web launcher was also observed
starting on port 3001, and API root dotenv loading was verified from `apps/api`.

Database/Redis/MinIO integration tests are opt-in and were not run against the
configured infrastructure. No real bootstrap
was executed, so existing organizations/accounts were not created or changed.
Live OAuth callbacks, paid AI calls, image uploads, and production ingress need
their deployment environment for end-to-end validation.

Production service examples retain web port 3100 and API port 8100 behind
OpenResty. Local development uses web port 3001 and API port 8000. Public
production origins and callback URLs must use the deployment's HTTPS hostname.
