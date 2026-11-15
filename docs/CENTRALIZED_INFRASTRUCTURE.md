# Centralized infrastructure integration

This application is designed to run on the `wisdom` host beside the existing
infrastructure containers. The application services run as unprivileged systemd
units on loopback; OpenResty remains the only public ingress.

## Service mapping

| Application setting | Existing service | Host endpoint |
|---|---|---|
| `DATABASE_URL` | `pgvector` (Postgres 17) | `127.0.0.1:5432` |
| `REDIS_URL` | `redis` | `127.0.0.1:6379` |
| `S3_ENDPOINT_URL` | `minio` | `127.0.0.1:9000` |
| `OPENAI_API_KEY` | Direct OpenAI API | `https://api.openai.com/v1` |
| optional `GEMINI_API_KEY` | Direct Gemini fallback | `https://generativelanguage.googleapis.com` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `otel-collector` | `http://127.0.0.1:4318` |
| `LANGFUSE_HOST` (optional) | Langfuse reverse proxy | `https://wisdom-dev.local/langfuse/` |

Langfuse is accessed through `https://wisdom-dev.local/langfuse/`; retain that
path prefix in `LANGFUSE_HOST`. Langfuse is optional and does not participate in
application readiness. The current application exports telemetry to the
OpenTelemetry collector independently. With `LANGFUSE_HOST` and both project
keys configured, generation and embedding spans also export directly to Langfuse.
These spans omit prompts, images, answers, field content, and exception messages.
Only task/provider/model, timing/status, and available token counts are exported.
Leave the host or either key empty to disable direct Langfuse export.

Leave `OTEL_EXPORTER_OTLP_ENDPOINT` empty to disable application telemetry export.
When set, optional exporter setup failures are logged without blocking API
startup. OIDC providers are optional in development and production. Staff phone/PIN
login is enabled by default through `STAFF_PIN_LOGIN_ENABLED=true`; set this to
`false` in both API and web environments for OIDC-only staff access.

## One-time platform preparation

1. Create a dedicated `agriverse` database and least-privilege application
   role in the existing Postgres container. The migration role must be able to
   create the `vector` extension and tables. The runtime role must not have
   `BYPASSRLS` or superuser privileges.
   Set `DATABASE_URL` to the runtime role and supply `MIGRATION_DATABASE_URL` only
   to administrative/migration commands. Alembic falls back to `DATABASE_URL`
   when a separate migration URL is absent. Local role provisioning is available
   through `apps/api/scripts/provision_runtime_role.py`; it generates a password,
   grants DML privileges, and verifies tenant isolation without changing ownership.
2. Create a dedicated Redis database or ACL identity for ARQ, rate limiting,
   OAuth exchanges, weather cache, and quota counters.
3. Create a private `agriverse` MinIO bucket and a scoped access key. The app
   also creates a missing bucket at startup, but production policy should be
   provisioned centrally.
4. Configure MinIO CORS for `https://agriverse.com`, allowing `PUT`, `GET`,
   `HEAD`, `Content-Type`, and `x-amz-server-side-encryption`. Presigned uploads
   require `AES256`.
5. Expose the MinIO S3 API through a TLS hostname such as
   `objects.agriverse.com`, or make another browser-reachable private endpoint.
   Set that URL as `S3_PUBLIC_ENDPOINT_URL`; keep `S3_ENDPOINT_URL` on loopback.
   In the local wisdom deployment, `/minio/` continues to serve port 9001's
   console. The bucket-specific snippet
   `deploy/openresty/agriverse-minio-api.inc` routes `/agriverse` and
   `/agriverse/...` unchanged to `minio:9000`; set the public endpoint to
   `https://wisdom-dev.local` without a prefix. Encrypted writes still require
   an encryption-capable AIStor license and server configuration. AIStor Free
   returns `405 XMinioPaidTierLicenseRequired` for AES256 writes. For local
   development against the existing Free setup, explicitly set
   `S3_SERVER_SIDE_ENCRYPTION=none` with `APP_ENV=development` and restart both
   API and worker. This omits server-side encryption for original and processed
   image objects; use synthetic test data. AES256 is the default, and staging
   and production refuse `none`.
6. Supply the production values from `.env.example` through process environment
   variables or a root-owned `/etc/agriverse/agriverse.env` (`0640`, group
   `agriverse`) loaded by the systemd units. No external secrets service is
   required. Keep production secrets outside the repository.

HTTPS clients use OS certificate trust. `TLS_CA_BUNDLE` can point to an additional
organization CA PEM bundle. The same verified roots are used by HTTPX, Authlib,
OpenAI/Gemini clients, S3 clients, and OTLP exporters. Certificate verification
remains enabled.

## Application installation

The examples assume `/srv/agriverse` is the release path:

```bash
corepack enable
corepack prepare pnpm@10.14.0 --activate
pnpm install --frozen-lockfile
pnpm build

cd /srv/agriverse/apps/api
uv sync --frozen --no-dev
uv run alembic upgrade head
```

Bootstrap the first organization only on an empty database. Supply
`BOOTSTRAP_NAME`, `BOOTSTRAP_PHONE`, `BOOTSTRAP_PIN` (6-12 digits), and optionally
`BOOTSTRAP_EMAIL` through the root `.env` or the process environment. The CLI
does not automatically load `/etc/agriverse/agriverse.env`; make these variables
available through the existing secret-delivery procedure before running it:

```bash
uv run python -m agriverse.cli bootstrap
```

The bootstrap administrator can sign in with phone/PIN in production when
`STAFF_PIN_LOGIN_ENABLED=true`. A configured OIDC provider is optional. For OIDC
sign-in, the email must match the first configured identity. Keycloak is supported; see
[AI and Keycloak setup](AI_AND_KEYCLOAK_SETUP.md).

Local development uses port 3001 for AgriVerse. Langfuse is accessed through
`https://wisdom-dev.local/langfuse/`.
The production units below retain their separate web/API upstream ports
3100/8100; set `WEB_ORIGIN`, `CORS_ORIGINS`, and OAuth callback URLs to the public
HTTPS application hostname in production.

Install the units and OpenResty route:

```bash
install -m 0644 deploy/systemd/agriverse-*.service /etc/systemd/system/
install -m 0644 deploy/openresty/agriverse.conf \
  /home/wisdom/Infra/openresty/conf.d/agriverse.conf
systemctl daemon-reload
systemctl enable --now agriverse-api agriverse-worker agriverse-web
docker exec openresty openresty -t
docker exec openresty openresty -s reload
```

If OpenResty is containerized without host networking, `127.0.0.1` inside the
container is not the host. Add the host gateway to the OpenResty Compose service
and replace the two upstream addresses with `host.docker.internal`, or attach
the application to a shared private Docker network.

## OIDC redirect URIs

Register these exact callback URLs with the selected providers:

- `https://agriverse.com/api/v1/auth/staff/oauth/google/callback`
- `https://agriverse.com/api/v1/auth/staff/oauth/microsoft/callback`

Set:

```dotenv
OAUTH_CALLBACK_BASE_URL=https://agriverse.com/api/v1
WEB_OAUTH_CALLBACK_URL=https://agriverse.com/api/oauth/callback
```

## Verification and rollback

Before routing traffic:

```bash
curl -fsS http://127.0.0.1:8100/healthz
curl -fsS http://127.0.0.1:8100/readyz
curl -I http://127.0.0.1:3100/
journalctl -u agriverse-api -u agriverse-worker -u agriverse-web -n 200
```

Readiness requires Postgres, Redis/ARQ, and MinIO. Roll back by restoring the
previous `/srv/agriverse` release symlink and restarting the three units. Schema
downgrades must be reviewed manually; do not automatically downgrade a
production database.
