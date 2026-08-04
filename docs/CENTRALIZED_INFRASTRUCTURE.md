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
| `OPENAI_BASE_URL` | `litellm` | `http://127.0.0.1:4000/v1` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `otel-collector` | `http://127.0.0.1:4318` |
| optional AI traces | `langfuse-web` | `http://127.0.0.1:3000` |

The unhealthy `langfuse-web` container does not block application readiness.
Resolve it before enabling Langfuse-specific tracing; OpenTelemetry export to
the collector continues independently.

## One-time platform preparation

1. Create a dedicated `agriverse` database and least-privilege application
   role in the existing Postgres container. The migration role must be able to
   create the `vector` extension and tables. The runtime role must not have
   `BYPASSRLS` or superuser privileges.
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
6. Store all production values from `.env.example` in Infisical. Materialize a
   root-owned `/etc/agriverse/agriverse.env` (`0640`, group `agriverse`) using
   the existing secret-delivery procedure. Do not store production secrets in
   the repository.

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

Bootstrap the first organization only on an empty database:

```bash
uv run python -m agriverse.cli bootstrap \
  --name "Organization name" \
  --phone "+919876543210" \
  --pin "replace-with-temporary-pin" \
  --email "admin@example.com"
```

The bootstrap PIN endpoint is disabled when `APP_ENV=production`. The email
must match the first Google or Microsoft OIDC identity.

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
