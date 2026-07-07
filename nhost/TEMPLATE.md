# Railway composer spec — Nhost

*The build-ready recipe for publishing this template in Railway's composer.
Follow top to bottom; validate with one test deploy before publishing. All
images, env vars, and values trace to upstream's docker-compose example and
`.env.example` (see Sources), adapted for Railway networking — deviations are
called out inline.*

Secret generation (verified syntax, Railway template docs):
`${{secret(length, "alphabet")}}` — e.g. hex: `${{secret(64, "abcdef0123456789")}}`.
Generate each secret **once**, on the service that "owns" it, and have the
other services reference it (`${{hasura.HASURA_GRAPHQL_ADMIN_SECRET}}`) so all
copies are identical.

## Services (6 — dashboard optional)

### 1. `Postgres`
- **Source:** Railway database → PostgreSQL (the built-in one)
- Nothing to configure at create time. **After first deploy** run the one-time
  bootstrap below (upstream ships it as an `initdb.d` script, which managed
  Postgres can't run automatically). It is idempotent.
- Connect with `railway connect Postgres` (or `psql "$DATABASE_PUBLIC_URL"`)
  and execute:

  ```sql
  -- verbatim from upstream initdb.d/0001-create-schema.sql
  CREATE SCHEMA IF NOT EXISTS auth;
  CREATE SCHEMA IF NOT EXISTS storage;
  -- https://github.com/hasura/graphql-engine/issues/3657
  CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;
  CREATE EXTENSION IF NOT EXISTS citext WITH SCHEMA public;
  CREATE OR REPLACE FUNCTION public.set_current_timestamp_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
  declare _new record;
  begin _new := new;
  _new."updated_at" = now();
  return _new;
  end;
  $$;
  ```

  *(Verify at test deploy: auth 0.40.x and storage 0.7.x may create their
  schemas via their own migrations, making this partially redundant — but the
  extensions-in-`public` part exists to dodge a known Hasura issue, so run it
  regardless. Deploy order below assumes you run it before auth/storage come
  up, or just let them crash-loop until you do.)*

### 2. `minio`  *(private S3 backend — create before storage)*
- **Source:** Docker image `minio/minio:RELEASE.2025-02-28T09-55-16Z`
- **Start command** (replicates upstream's entrypoint override, which
  pre-creates the bucket directory):
  ```
  /bin/sh -c "mkdir -p /data/nhost && /usr/bin/minio server --address :9000 /data"
  ```
- **Variables:**
  - `MINIO_ROOT_USER` = `${{secret(20, "abcdefghijklmnopqrstuvwxyz0123456789")}}`
  - `MINIO_ROOT_PASSWORD` = `${{secret(40)}}`
- **Volume:** mount at `/data`
- **Networking:** NO public domain. Private only, port 9000. MinIO is Go and
  `--address :9000` binds the wildcard (dual-stack), so it should be reachable
  over Railway's IPv6-first private network — **verify at test deploy** that
  storage can reach `http://minio.railway.internal:9000`.

### 3. `hasura`
- **Source:** Docker image `nhost/graphql-engine:v2.46.0-ce`
  (Nhost's build of Hasura CE; upstream pins this tag)
- **Start command:** none (image default). Hasura's default
  `HASURA_GRAPHQL_SERVER_HOST` is `*` and port is 8080 (Hasura docs) — listens
  on all interfaces, so it serves both the public edge and private dials from
  auth/storage. **Verify at test deploy** that `*` covers IPv6 on Railway's
  private network.
- **Variables** (upstream compose list; deviations noted):
  - `HASURA_GRAPHQL_DATABASE_URL` = `${{Postgres.DATABASE_URL}}`
  - `HASURA_GRAPHQL_ADMIN_SECRET` = `${{secret(32)}}`  ← *the* admin secret; other services reference it
  - `HASURA_GRAPHQL_JWT_SECRET` = `{"type":"HS256","key":"${{secret(64, "abcdef0123456789")}}"}`  ← *the* JWT secret (see gotcha 1)
  - `HASURA_GRAPHQL_ADMIN_INTERNAL_ERRORS` = `true`
  - `HASURA_GRAPHQL_CONSOLE_ASSETS_DIR` = `/srv/console-assets`
  - `HASURA_GRAPHQL_CORS_DOMAIN` = `*`  (tighten to your app's origin in production)
  - `HASURA_GRAPHQL_DEV_MODE` = `false`  (upstream demo: `true`; flipped for production)
  - `HASURA_GRAPHQL_DISABLE_CORS` = `false`
  - `HASURA_GRAPHQL_ENABLE_ALLOWLIST` = `false`
  - `HASURA_GRAPHQL_ENABLE_CONSOLE` = `true`  (admin-secret protected; replaces the excluded hasura-cli console sidecar)
  - `HASURA_GRAPHQL_ENABLE_REMOTE_SCHEMA_PERMISSIONS` = `false`
  - `HASURA_GRAPHQL_ENABLE_TELEMETRY` = `false`
  - `HASURA_GRAPHQL_ENABLED_APIS` = `metadata,graphql,pgdump,config`
  - `HASURA_GRAPHQL_ENABLED_LOG_TYPES` = `startup,http-log,webhook-log,websocket-log`
  - `HASURA_GRAPHQL_EVENTS_HTTP_POOL_SIZE` = `100`
  - `HASURA_GRAPHQL_INFER_FUNCTION_PERMISSIONS` = `true`
  - `HASURA_GRAPHQL_LIVE_QUERIES_MULTIPLEXED_BATCH_SIZE` = `100`
  - `HASURA_GRAPHQL_LIVE_QUERIES_MULTIPLEXED_REFETCH_INTERVAL` = `1000`
  - `HASURA_GRAPHQL_LOG_LEVEL` = `warn`
  - `HASURA_GRAPHQL_PG_CONNECTIONS` = `50`
  - `HASURA_GRAPHQL_PG_TIMEOUT` = `180`
  - `HASURA_GRAPHQL_STRINGIFY_NUMERIC_TYPES` = `false`
  - `HASURA_GRAPHQL_TX_ISOLATION` = `read-committed`
  - `HASURA_GRAPHQL_UNAUTHORIZED_ROLE` = `public`
  - `HASURA_GRAPHQL_USE_PREPARED_STATEMENTS` = `true`
  - `HASURA_GRAPHQL_WS_READ_COOKIE` = `false`
  - *(Omitted: `GRAPHITE_WEBHOOK_SECRET` — Nhost Cloud AI feature, empty string upstream.)*
- **Networking:** public domain ON, target port 8080. Also dialed privately by
  auth and storage on 8080.
- **Healthcheck path:** `/healthz`

### 4. `auth`
- **Source:** Docker image `nhost/auth:0.40.2`
- **Variables** (full upstream list; Railway wiring noted):
  - `HASURA_GRAPHQL_DATABASE_URL` = `${{Postgres.DATABASE_URL}}`
  - `POSTGRES_MIGRATIONS_CONNECTION` = `${{Postgres.DATABASE_URL}}`  (auth applies its own schema migrations at startup)
  - `HASURA_GRAPHQL_GRAPHQL_URL` = `http://${{hasura.RAILWAY_PRIVATE_DOMAIN}}:8080/v1/graphql`
  - `HASURA_GRAPHQL_JWT_SECRET` = `${{hasura.HASURA_GRAPHQL_JWT_SECRET}}`
  - `HASURA_GRAPHQL_ADMIN_SECRET` = `${{hasura.HASURA_GRAPHQL_ADMIN_SECRET}}`
  - `AUTH_HOST` = `0.0.0.0`  (only receives public edge traffic; nothing dials it privately)
  - `AUTH_PORT` = `4000`
  - `AUTH_API_PREFIX` = `/v1`
  - `AUTH_SERVER_URL` = `https://${{RAILWAY_PUBLIC_DOMAIN}}/v1`  (self-reference)
  - `AUTH_CLIENT_URL` = `http://localhost:3000`  ← **deployer must change** to their frontend URL
  - `AUTH_ACCESS_TOKEN_EXPIRES_IN` = `900`
  - `AUTH_REFRESH_TOKEN_EXPIRES_IN` = `2592000`
  - `AUTH_ANONYMOUS_USERS_ENABLED` = `false`
  - `AUTH_CONCEAL_ERRORS` = `false`  (consider `true` in production)
  - `AUTH_DISABLE_NEW_USERS` = `false`
  - `AUTH_DISABLE_SIGNUP` = `false`
  - `AUTH_EMAIL_PASSWORDLESS_ENABLED` = `false`
  - `AUTH_EMAIL_SIGNIN_EMAIL_VERIFIED_REQUIRED` = `false`  (flip to `true` once SMTP works)
  - `AUTH_OTP_EMAIL_ENABLED` = `false`
  - `AUTH_GRAVATAR_ENABLED` = `true`, `AUTH_GRAVATAR_DEFAULT` = `blank`, `AUTH_GRAVATAR_RATING` = `g`
  - `AUTH_JWT_CUSTOM_CLAIMS` = `{}`
  - `AUTH_LOCALE_DEFAULT` = `en`, `AUTH_LOCALE_ALLOWED_LOCALES` = `en`
  - `AUTH_MFA_ENABLED` = `false`, `AUTH_MFA_TOTP_ISSUER` = *(empty)*
  - `AUTH_PASSWORD_MIN_LENGTH` = `9`, `AUTH_PASSWORD_HIBP_ENABLED` = `false`
  - `AUTH_USER_DEFAULT_ROLE` = `user`, `AUTH_USER_DEFAULT_ALLOWED_ROLES` = `user,me`
  - `AUTH_REQUIRE_ELEVATED_CLAIM` = `disabled`
  - `AUTH_TURNSTILE_SECRET` = *(empty)*
  - Access control (all empty strings upstream): `AUTH_ACCESS_CONTROL_ALLOWED_EMAIL_DOMAINS`, `AUTH_ACCESS_CONTROL_ALLOWED_EMAILS`, `AUTH_ACCESS_CONTROL_ALLOWED_REDIRECT_URLS`, `AUTH_ACCESS_CONTROL_BLOCKED_EMAIL_DOMAINS`, `AUTH_ACCESS_CONTROL_BLOCKED_EMAILS`
  - Rate limits (upstream defaults): `AUTH_RATE_LIMIT_ENABLE` = `true`, `AUTH_RATE_LIMIT_GLOBAL_BURST` = `100`, `AUTH_RATE_LIMIT_GLOBAL_INTERVAL` = `1m`, `AUTH_RATE_LIMIT_BRUTE_FORCE_BURST` = `10`, `AUTH_RATE_LIMIT_BRUTE_FORCE_INTERVAL` = `5m`, `AUTH_RATE_LIMIT_EMAIL_BURST` = `10`, `AUTH_RATE_LIMIT_EMAIL_INTERVAL` = `1h`, `AUTH_RATE_LIMIT_EMAIL_IS_GLOBAL` = `true`, `AUTH_RATE_LIMIT_SIGNUPS_BURST` = `10`, `AUTH_RATE_LIMIT_SIGNUPS_INTERVAL` = `5m`, `AUTH_RATE_LIMIT_SMS_BURST` = `10`, `AUTH_RATE_LIMIT_SMS_INTERVAL` = `1h`
  - SMTP (upstream points these at Mailhog; deployer supplies real values):
    `AUTH_SMTP_HOST`, `AUTH_SMTP_PORT` = `587`, `AUTH_SMTP_USER`,
    `AUTH_SMTP_PASS`, `AUTH_SMTP_SENDER`, `AUTH_SMTP_SECURE` = `false`,
    `AUTH_SMTP_AUTH_METHOD` = `LOGIN`
  - *(Omitted: the email-templates bind mount `nhost/emails:/app/email-templates` — built-in templates are used; fork + custom image to customize.)*
- **Networking:** public domain ON, target port 4000.
- **Healthcheck path:** `/healthz`

### 5. `storage`
- **Source:** Docker image `nhost/storage:0.7.2`
- **Start command:** `serve`  (the image's compose invocation passes `serve` as the command)
- **Variables:**
  - `BIND` = `:5000`
  - `PUBLIC_URL` = `https://${{RAILWAY_PUBLIC_DOMAIN}}`  (self-reference)
  - `HASURA_ENDPOINT` = `http://${{hasura.RAILWAY_PRIVATE_DOMAIN}}:8080/v1`  (note: `/v1`, not `/v1/graphql`)
  - `HASURA_GRAPHQL_ADMIN_SECRET` = `${{hasura.HASURA_GRAPHQL_ADMIN_SECRET}}`
  - `HASURA_METADATA` = `1`  (auto-applies its Hasura metadata — files/buckets tables get tracked)
  - `POSTGRES_MIGRATIONS` = `1`  (auto-applies its own schema migrations)
  - `POSTGRES_MIGRATIONS_SOURCE` = `${{Postgres.DATABASE_URL}}?sslmode=disable`  (upstream appends `sslmode=disable`; see gotcha 4)
  - `S3_ACCESS_KEY` = `${{minio.MINIO_ROOT_USER}}`
  - `S3_SECRET_KEY` = `${{minio.MINIO_ROOT_PASSWORD}}`
  - `S3_ENDPOINT` = `http://${{minio.RAILWAY_PRIVATE_DOMAIN}}:9000`
  - `S3_BUCKET` = `nhost`
  - `S3_REGION` = *(empty)*
  - `S3_ROOT_FOLDER` = *(empty)*
- **Networking:** public domain ON, target port 5000 (browsers upload directly).
- **Healthcheck path:** `/healthz`  *(verify at test deploy; `/v1/version` confirmed upstream)*

### 6. `dashboard`  *(optional — read the security warning, gotcha 6)*
- **Source:** Docker image `nhost/dashboard:2.34.0`
- **Variables** (all `NEXT_PUBLIC_*` — i.e. visible to every browser that loads the page):
  - `NEXT_PUBLIC_NHOST_PLATFORM` = `false`
  - `NEXT_PUBLIC_ENV` = `dev`  (upstream value; cloud-only options render greyed out)
  - `NEXT_PUBLIC_NHOST_ADMIN_SECRET` = `${{hasura.HASURA_GRAPHQL_ADMIN_SECRET}}`
  - `NEXT_PUBLIC_NHOST_AUTH_URL` = `https://${{auth.RAILWAY_PUBLIC_DOMAIN}}/v1`
  - `NEXT_PUBLIC_NHOST_GRAPHQL_URL` = `https://${{hasura.RAILWAY_PUBLIC_DOMAIN}}/v1/graphql`
  - `NEXT_PUBLIC_NHOST_STORAGE_URL` = `https://${{storage.RAILWAY_PUBLIC_DOMAIN}}/v1`
  - `NEXT_PUBLIC_NHOST_FUNCTIONS_URL` = `https://${{hasura.RAILWAY_PUBLIC_DOMAIN}}/v1`  ← placeholder; functions are excluded (see README). Point at your own functions deployment if you add one.
  - `NEXT_PUBLIC_NHOST_HASURA_API_URL` = `https://${{hasura.RAILWAY_PUBLIC_DOMAIN}}`
  - `NEXT_PUBLIC_NHOST_HASURA_CONSOLE_URL` = `https://${{hasura.RAILWAY_PUBLIC_DOMAIN}}/console`
  - `NEXT_PUBLIC_NHOST_HASURA_MIGRATIONS_API_URL` = `https://${{hasura.RAILWAY_PUBLIC_DOMAIN}}`  ← upstream routes this to the hasura-cli console sidecar, which is excluded; dashboard features that need the migrations API may not work (gotcha 7)
- **Networking:** public domain ON, target port 3000.

## Deploy order

Postgres → run bootstrap SQL → minio → hasura → auth → storage → dashboard.
Railway starts everything at once on template deploy; auth/storage crash-loop
until Postgres + hasura are up, then settle (same pattern as our Dagster
template — don't add init hacks). If auth keeps failing after hasura is
healthy, you probably skipped the bootstrap SQL.

## Gotchas (check during the test deploy)

1. **JWT secret format is the #1 footgun.** The value is a JSON *object as a
   string*: `{"type":"HS256","key":"<64 hex chars>"}` (format confirmed in
   upstream `.env.example` and Hasura docs). No surrounding quotes, no
   escaping, key ≥ 32 bytes. Auth **signs** with it, hasura **verifies** — if
   they differ by one byte, every request is `Could not verify JWT`. That's
   why the template defines it once on hasura and auth references it.
   *(Verify at test deploy: the composer accepts a `${{secret(...)}}` call
   embedded inside a JSON string. If it doesn't, generate with
   `openssl rand -hex 32` and paste the literal into both services.)*
   Fun fact: upstream's `.env.example` says `openssl rand -base10 32` — that
   flag doesn't exist; use `-hex 32`.
2. **One database, three writers.** Hasura, auth, and storage all point at the
   same Postgres database (`${{Postgres.DATABASE_URL}}`). Auth owns the `auth`
   schema, storage owns `storage`, your app lives in `public`. Do not give
   them separate databases — auth/storage metadata must be trackable by the
   same Hasura instance.
3. **Bootstrap SQL before first success.** Managed Postgres can't run
   upstream's `initdb.d` script; run it manually (service 1). Idempotent, safe
   to re-run.
4. **`sslmode` on the Go migration connections.** Upstream appends
   `?sslmode=disable` to storage's `POSTGRES_MIGRATIONS_SOURCE`. Railway's
   private-network Postgres connection needs no TLS. If auth's migrations fail
   with an SSL/TLS error, append `?sslmode=disable` to
   `POSTGRES_MIGRATIONS_CONNECTION` too (verify at test deploy).
5. **Private network is IPv6-first.** Services dialed over
   `*.railway.internal` must listen on IPv6. Should be fine here — hasura's
   default host is `*`, MinIO/storage are Go binaries binding wildcard
   addresses — but if storage can't reach minio or auth can't reach hasura,
   suspect the bind address first (we hit exactly this class of bug in the
   Dagster template).
6. **The dashboard leaks the admin secret by design.** Upstream injects
   `NEXT_PUBLIC_NHOST_ADMIN_SECRET` into a Next.js app — anyone who can load
   the dashboard URL can read your Hasura admin secret from the page source.
   There is no built-in login on the self-hosted dashboard. Treat the
   dashboard URL as a secret, put it behind an access layer, or delete the
   service. This is called out in the marketplace description too.
7. **Migrations/metadata bootstrapping is automatic — mostly.** Auth applies
   its own DB migrations (`POSTGRES_MIGRATIONS_CONNECTION`); storage applies
   both DB migrations (`POSTGRES_MIGRATIONS=1`) and Hasura metadata
   (`HASURA_METADATA=1`), which is how `users`/`files`/`buckets` become
   queryable via GraphQL. What is *not* automatic: the hasura-cli
   migrations-API workflow (excluded sidecar), so dashboard database editing
   may error — use the Hasura console at `/console` for schema work.
8. **No path rewrites without Traefik.** GraphQL clients must use the full
   `https://<hasura-domain>/v1/graphql`. Upstream's proxy also exposed
   Hasura's `/v1/version`; that works directly too. Auth (`/v1/...`) and
   storage (`/v1/...`) serve their prefixes natively.
9. **MinIO bucket creation.** The start command `mkdir -p /data/nhost`
   replicates upstream's bucket bootstrap. Verify at test deploy that the
   first upload succeeds; if MinIO's newer single-drive mode doesn't accept a
   bare directory as a bucket, create it properly once:
   `mc alias set local http://minio.railway.internal:9000 $USER $PASS && mc mb local/nhost`
   (or just retry after using the MinIO console via `railway connect`).

## Post-deploy verification checklist

- [ ] Bootstrap SQL executed against Postgres (service 1)
- [ ] `curl https://<hasura-domain>/healthz` → 200; `/v1/version` returns `{"server_type":"ce",...}`
- [ ] Hasura console loads at `https://<hasura-domain>/console` with the admin secret
- [ ] `curl https://<auth-domain>/v1/version` returns a version
- [ ] Signup works:
  ```
  curl -X POST https://<auth-domain>/v1/signup/email-password \
    -H "Content-Type: application/json" \
    -d '{"email":"email@acme.test","password":"s3cur3p4ssw0rd!"}'
  ```
  → returns a session with `accessToken` (decode it: claims include
  `x-hasura-default-role: user`)
- [ ] GraphQL sees the user:
  ```
  curl -X POST https://<hasura-domain>/v1/graphql \
    -H "X-Hasura-Admin-Secret: <admin-secret>" \
    -d '{"query":"query { users { id email } }"}'
  ```
- [ ] File upload works (proves storage → minio and storage → hasura wiring):
  ```
  curl -X POST https://<storage-domain>/v1/files \
    -H "X-Hasura-Admin-Secret: <admin-secret>" \
    -F "file=@README.md"
  ```
  → returns file metadata with `"isUploaded": true`
- [ ] Dashboard (if deployed) loads and lists the signed-up user
- [ ] Using the signup's `accessToken` as `Authorization: Bearer` against
  GraphQL returns data (JWT secret wiring confirmed end-to-end)

## Marketplace listing

- **Name:** Nhost
- **Category:** Backend as a Service / Databases (closest available)
- **Overview (draft):** "The open-source Firebase alternative, deployed the way
  Nhost actually runs it: Postgres + Hasura GraphQL + Hasura Auth + Hasura
  Storage backed by MinIO, with the Nhost Dashboard as an optional admin UI.
  JWT and admin secrets are generated and wired across all services at deploy
  time. Sign up users, query them over GraphQL, and upload files within
  minutes of deploying. One manual step: run a 10-line SQL bootstrap after
  first deploy (instructions included). Serverless functions are not included
  in v1 — deploy your API as a separate Railway service. Note: the optional
  dashboard embeds the admin secret in its client bundle (upstream design);
  keep its URL private or remove the service."
- Enable the kickback option when publishing; support requests come through
  the Template Queue.

## Maintenance

- All images are official upstream images pinned to the tags from Nhost's
  example compose (no custom builds in this repo for this template). Watch
  [nhost/nhost releases](https://github.com/nhost/nhost/releases) — auth and
  storage development moved into the monorepo (their standalone repos are
  archived).
- Known-newer tags at time of writing (2026-07-07, Docker Hub): auth `0.50.1`,
  storage `0.15.0`, dashboard `3.0.0`, graphql-engine `v2.49.2-ce`. Bump the
  whole set together after a test deploy, since upstream tests these as a
  unit; auth/storage self-migrate their schemas on startup.
- If deploy success rate drops, diff upstream's
  `examples/docker-compose/docker-compose.yaml` against this spec first — env
  var names have churned before (e.g. the image rename
  `nhost/hasura-auth` → `nhost/auth`).

## Sources (fetched 2026-07-07)

- Upstream compose (all services, images, env vars, ports, volumes):
  https://github.com/nhost/nhost/blob/main/examples/docker-compose/docker-compose.yaml
- Secret formats + JWT example:
  https://github.com/nhost/nhost/blob/main/examples/docker-compose/.env.example
- Demo framing, endpoints, verification curl commands:
  https://github.com/nhost/nhost/blob/main/examples/docker-compose/README.md
- Bootstrap SQL:
  https://github.com/nhost/nhost/blob/main/examples/docker-compose/initdb.d/0001-create-schema.sql
- Auth service (MIT, archived → monorepo): https://github.com/nhost/hasura-auth
- Storage service (Apache-2.0, archived → monorepo): https://github.com/nhost/hasura-storage
- Current image tags: https://hub.docker.com/r/nhost/auth/tags (and storage,
  dashboard, graphql-engine, functions)
- Railway `secret()` function syntax: https://docs.railway.com/templates/create
- Railway reference variables + `RAILWAY_PUBLIC_DOMAIN`/`RAILWAY_PRIVATE_DOMAIN`:
  https://docs.railway.com/variables/reference
- Hasura server host/port defaults + JWT secret format:
  https://hasura.io/docs/2.0/deployment/graphql-engine-flags/reference/
