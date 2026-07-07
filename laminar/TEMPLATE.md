# Railway composer spec — Laminar

*The build-ready recipe for publishing this template in Railway's composer.
Mirrors upstream `docker-compose-full.yml` (fetched 2026-07-07). Follow top to
bottom; validate with one test deploy before publishing.*

Service names below deliberately match upstream compose hostnames
(`clickhouse`, `rabbitmq`, `quickwit`, `app-server`, `frontend`) so the
private domains read like the compose file. All cross-service values are
wired with reference variables — nothing is hardcoded.

## Services (6)

### 1. `Postgres`
- **Source:** Railway database → PostgreSQL (the built-in one).
- Nothing else to configure. Upstream compose pins `postgres:16`; Railway's
  built-in may deploy a newer major — Laminar's migrations are plain
  Drizzle-generated SQL and expected to apply cleanly, but **verify at test
  deploy** (watch the frontend's boot logs, which run the migrations).

### 2. `clickhouse`
- **Source:** Docker image `ghcr.io/brunoban/railway-laminar-clickhouse:latest`
  (built by CI from [`Dockerfile`](Dockerfile) in this directory — see
  *CI workflow* below; base is upstream's pinned `clickhouse/clickhouse-server:26.5`).
- **Variables:**
  - `CLICKHOUSE_USER` = `lmnr`
  - `CLICKHOUSE_PASSWORD` = `${{secret()}}`
- **Volume:** mount at `/var/lib/clickhouse` (upstream also volumes
  `/var/log/clickhouse-server`, but Railway allows one volume per service —
  logs are ephemeral, acceptable loss; see gotcha 4).
- **Networking:** private only, port 8123 (HTTP). **No public domain, no TCP
  proxy.**
- **Note:** upstream compose grants `SYS_NICE`/`NET_ADMIN`/`IPC_LOCK` caps and
  raises `nofile` to 262144. Railway can grant neither — see gotcha 3.

### 3. `rabbitmq`
- **Source:** Docker image `rabbitmq:4`
  (upstream compose uses the untagged `rabbitmq` image, i.e. `latest`, which
  is the 4.x line on Docker Hub as of 2026-07 — pinning the major is the
  template-stability tradeoff).
- **Variables:**
  - `RABBITMQ_DEFAULT_USER` = `laminar`
  - `RABBITMQ_DEFAULT_PASS` = `${{secret()}}`
- **Volume:** none — upstream's compose runs RabbitMQ without one (transient
  span queue). Spans buffered in the queue at restart time are lost; add a
  volume at `/var/lib/rabbitmq` only if that bothers you.
- **Networking:** private only, port 5672. **No public domain, no TCP proxy.**

### 4. `quickwit`
- **Source:** Docker image `quickwit/quickwit:v0.8.2` (upstream's pinned tag).
- **Start command:** `run`
  (the image's ENTRYPOINT is the `quickwit` binary and upstream compose sets
  `command: ["run"]`; Railway's custom start command replaces CMD i.e. the
  entrypoint args — **verify at test deploy** that the service boots with
  just `run`, otherwise try `quickwit run`).
- **Variables:**
  - `QW_DATA_DIR` = `/quickwit/qwdata` (matches compose; also the image default)
- **Volume:** mount at `/quickwit/qwdata`.
- **Networking:** private only, ports 7280 (REST) and 7281 (OTLP/gRPC —
  private networking has no protocol restrictions, so app-server's gRPC
  ingest to 7281 is fine). **No public domain, no TCP proxy.**

### 5. `app-server`
- **Source:** Docker image `ghcr.io/lmnr-ai/app-server:latest`
  (upstream compose uses the untagged image = `latest`; versioned tags like
  `v0.1.13` exist but lag `latest`, and upstream self-hosting tracks `latest` —
  keep it, and upgrade in lockstep with `frontend`).
- **Variables:**
  - `PORT` = `8000`
  - `GRPC_PORT` = `8001`
  - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}`
  - `RABBITMQ_URL` = `amqp://${{rabbitmq.RABBITMQ_DEFAULT_USER}}:${{rabbitmq.RABBITMQ_DEFAULT_PASS}}@${{rabbitmq.RAILWAY_PRIVATE_DOMAIN}}:5672/%2f`
  - `CLICKHOUSE_URL` = `http://${{clickhouse.RAILWAY_PRIVATE_DOMAIN}}:8123`
  - `CLICKHOUSE_USER` = `${{clickhouse.CLICKHOUSE_USER}}`
  - `CLICKHOUSE_PASSWORD` = `${{clickhouse.CLICKHOUSE_PASSWORD}}`
  - `CLICKHOUSE_RO_USER` = `${{clickhouse.CLICKHOUSE_USER}}`
  - `CLICKHOUSE_RO_PASSWORD` = `${{clickhouse.CLICKHOUSE_PASSWORD}}`
    (upstream self-host provisions no separate read-only user — its
    `app-server/.env.example` sets both pairs to the same `ch_user`)
  - `SHARED_SECRET_TOKEN` = `${{secret()}}`
  - `AEAD_SECRET_KEY` = `${{secret(64, "abcdef0123456789")}}`
    (must be exactly 32 bytes / 64 hex chars per `app-server/.env.example`)
  - `ENVIRONMENT` = `FULL`
  - `QUICKWIT_SEARCH_URL` = `http://${{quickwit.RAILWAY_PRIVATE_DOMAIN}}:7280`
  - `QUICKWIT_INGEST_URL` = `http://${{quickwit.RAILWAY_PRIVATE_DOMAIN}}:7281`
  - `QUICKWIT_SPANS_INDEX_ID` = `spans_v2`
- **Networking:** public domain ON, target port **8000** — SDKs and OTLP
  exporters running in user infra send traces here (over HTTP with
  `forceHttp`; see gotcha 1). Ports 8001 (gRPC) and 8002 (realtime, env name
  `CONSUMER_PORT`, default 8002) stay private; the frontend dials 8000/8002
  over the private network.
- **Sizing:** 512MB–1GB — it spawns many queue-consumer workers.

### 6. `frontend`  *(create last — it runs all migrations at boot)*
- **Source:** Docker image `ghcr.io/lmnr-ai/frontend:latest` (same lockstep
  rule as app-server).
- **Variables:**
  - `PORT` = `5667`
  - `BACKEND_URL` = `http://${{app-server.RAILWAY_PRIVATE_DOMAIN}}:8000`
  - `BACKEND_RT_URL` = `http://${{app-server.RAILWAY_PRIVATE_DOMAIN}}:8002`
  - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}`
  - `SHARED_SECRET_TOKEN` = `${{app-server.SHARED_SECRET_TOKEN}}`
  - `AEAD_SECRET_KEY` = `${{app-server.AEAD_SECRET_KEY}}` (must match app-server)
  - `BETTER_AUTH_URL` = `https://${{RAILWAY_PUBLIC_DOMAIN}}`
  - `BETTER_AUTH_SECRET` = `${{secret()}}`
    (auth is Better Auth; upstream compose still sets legacy `NEXTAUTH_URL`/
    `NEXTAUTH_SECRET`, which `frontend/lib/auth.ts` reads as fallbacks —
    we set the canonical names)
  - `NEXT_PUBLIC_URL` = `https://${{RAILWAY_PUBLIC_DOMAIN}}`
  - `ENVIRONMENT` = `FULL`
  - `CLICKHOUSE_URL` = `http://${{clickhouse.RAILWAY_PRIVATE_DOMAIN}}:8123`
  - `CLICKHOUSE_USER` = `${{clickhouse.CLICKHOUSE_USER}}`
  - `CLICKHOUSE_PASSWORD` = `${{clickhouse.CLICKHOUSE_PASSWORD}}`
  - `QUICKWIT_SEARCH_URL` = `http://${{quickwit.RAILWAY_PRIVATE_DOMAIN}}:7280`
  - Optional, exposed as template inputs (all read by the frontend per
    upstream compose): `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_BASE_URL`,
    `LLM_MODEL_SMALL`, `LLM_MODEL_MEDIUM`, `LLM_MODEL_LARGE`, `AWS_REGION`,
    `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `OPENAI_API_KEY`
- **Networking:** public domain ON (this is the UI), target port 5667. The
  browser never talks to app-server directly — `BACKEND_URL`/`BACKEND_RT_URL`
  are server-side-only vars and there are no `NEXT_PUBLIC_*` backend URLs in
  upstream's compose.

## Gotchas (check these during the test deploy)

1. **No gRPC through Railway's HTTPS edge.** Railway's public proxy speaks
   HTTP/1.1 to upstreams, so the SDKs' default gRPC span exporter (port 8001)
   cannot go through the app-server's public domain. Both SDKs support HTTP
   export — Python `force_http=True`, TS `forceHttp: true` (+ `httpPort`), and
   the app-server serves `POST /v1/traces` on its HTTP port — so the
   documented setup is HTTP-only via the single public domain on port 8000.
   A Railway TCP proxy on 8001 would carry raw gRPC but **plaintext over the
   public internet** — do not add it to the template; mention it only if a
   user insists and understands the tradeoff.
2. **IPv4 binds vs. Railway private networking.** `app-server` binds `0.0.0.0`
   on all three ports (verified in `app-server/src/main.rs`), and the Quickwit
   image bakes `QW_LISTEN_ADDRESS=0.0.0.0` — both IPv4-only. Railway
   environments created after 2025-10-16 resolve `*.railway.internal` to both
   private IPv4 and IPv6, so these should be reachable; legacy IPv6-only
   environments would not reach them. Binding behavior varies by stack (cf.
   the Dagster template, where `::` vs `0.0.0.0` differed per process), so
   **verify at test deploy**: frontend → app-server:8000/8002 and
   app-server → quickwit:7280/7281. If Quickwit is unreachable, set
   `QW_LISTEN_ADDRESS` = `::` on the quickwit service; if app-server is
   unreachable there is no bind-address env — that would need an upstream
   patch (unlikely to be needed on a fresh, dual-stack environment).
   ClickHouse (image config listens `::` + `0.0.0.0` with `listen_try`) and
   RabbitMQ (listens on all interfaces by default) are fine either way.
3. **ClickHouse capabilities and ulimits are dropped — deliberately.**
   Upstream compose adds `SYS_NICE`/`NET_ADMIN`/`IPC_LOCK` and raises
   `nofile` to 262144. Railway cannot grant capabilities or set ulimits.
   ClickHouse runs without them (expect startup warnings like "CAP_SYS_NICE
   not set", losing only scheduling/memory-locking niceties). Do not "fix"
   this. Confirm at test deploy that the platform's default `nofile` doesn't
   trip ClickHouse (it logs a warning if too low).
4. **One volume per service** (Railway constraint): ClickHouse keeps
   `/var/lib/clickhouse`; upstream's second volume (`/var/log/clickhouse-server`)
   is dropped — logs also go to stderr, nothing durable is lost.
5. **First-boot order.** Railway has no `depends_on`. The frontend owns all
   schema: Drizzle Postgres migrations + ClickHouse migrations run at frontend
   startup (`instrumentation.ts`), and Quickwit indexes (`spans_v2`,
   `signal_events`) are created at frontend boot (`initializeQuickwitIndexes`).
   app-server may crash-loop or log errors until Postgres/RabbitMQ/ClickHouse/
   Quickwit are up and the frontend has run migrations once. Railway restarts
   it and the stack settles. Acceptable; do not add init hacks.
6. **`latest` is upstream's supported tag.** GHCR `latest` digests differ from
   the newest versioned tag (`v0.1.13` at scaffold time) — upstream pushes
   `latest` ahead of releases and the compose file tracks it. Keep both
   Laminar images on `latest` and redeploy the pair together (gotcha 5's
   migration coupling is why mixed versions are risky).
7. **Service renames break the wiring semantics, not the references.**
   Reference variables follow the service, but the names were chosen to match
   upstream compose hostnames — keep them, so logs and docs line up.
8. **Auth is open by default.** Self-hosted Laminar lets any user sign up/in
   (upstream-documented behavior). The marketplace listing must say so and
   point at the `AUTH_GITHUB_*` (and Google/Okta/Keycloak) frontend vars.

## Post-deploy verification checklist

- [ ] Frontend loads on its public domain; sign-up/sign-in works
- [ ] Frontend boot logs: Postgres (Drizzle) + ClickHouse migrations applied,
      Quickwit indexes created — no errors
- [ ] app-server logs settle: RabbitMQ connected, workers started
      ("Spans workers: …" log line)
- [ ] Create a project → generate a project API key
- [ ] From a laptop: `Laminar.initialize(base_url="https://<app-server domain>",
      force_http=True, project_api_key=...)` + one `@observe` call → trace
      appears in the UI (proves public HTTP ingest + queue + ClickHouse write)
- [ ] Open the trace while it's running → realtime view streams
      (proves frontend → app-server:8002 private dial, gotcha 2)
- [ ] Full-text search over the new span returns it (proves Quickwit ingest +
      search round-trip)
- [ ] Restart every service once → all recover, data still present
      (volumes hold)

## Marketplace listing

- **Name:** Laminar
- **Category:** AI/ML (or Observability if available)
- **Overview (draft):** "Laminar (lmnr) — open-source observability for LLM
  apps and AI agents: OpenTelemetry tracing, evals, datasets, dashboards, and
  full-text span search. This is the real production stack from upstream's
  docker-compose-full.yml — frontend + Rust app-server backed by Postgres,
  ClickHouse, Quickwit, and RabbitMQ — not the single-container quickstart.
  Point the lmnr SDK at your app-server domain with `forceHttp` and traces
  flow. Note: self-hosted auth is open by default; configure OAuth env vars
  before sharing the URL. Apache-2.0 upstream."
- Enable the kickback option when publishing; support requests come through
  the Template Queue.

## Maintenance

- **CI image:** `ghcr.io/brunoban/railway-laminar-clickhouse:latest` rebuilds
  on pushes to `laminar/**` once the workflow below is added. It's a one-line
  overlay on `clickhouse/clickhouse-server:26.5`; bump the base tag when
  upstream's compose bumps theirs.
- Watch `lmnr-ai/lmnr` for changes to `docker-compose-full.yml` — new env
  vars, the ClickHouse/Quickwit tag pins, and the profiles XML are the drift
  points (diff against the Sources snapshot below). The frontend/app-server
  images self-update on `latest`; template redeploys pick them up.
- Auth env vars have already migrated once (`NEXTAUTH_*` → `BETTER_AUTH_*`
  with fallback). If sign-in breaks after an upstream release, check
  `frontend/lib/auth.ts` first.
- If deploy success rate drops on the template dashboard, check upstream
  breaking changes before touching the wiring.

### CI workflow to add (not created by this scaffold)

This scaffold writes nothing outside `laminar/`. Add
`.github/workflows/build-laminar-clickhouse.yml` at repo root with exactly
this content (same pattern as `build-dagster.yml`):

```yaml
name: Build laminar clickhouse image

on:
  push:
    branches: [main]
    paths:
      - "laminar/**"
      - ".github/workflows/build-laminar-clickhouse.yml"
  workflow_dispatch:

permissions:
  contents: read
  packages: write

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: docker/setup-buildx-action@v3

      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - uses: docker/build-push-action@v6
        with:
          context: ./laminar
          push: true
          tags: |
            ghcr.io/${{ github.repository_owner }}/railway-laminar-clickhouse:latest
            ghcr.io/${{ github.repository_owner }}/railway-laminar-clickhouse:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

## Sources (fetched 2026-07-07)

Upstream Laminar:
- https://raw.githubusercontent.com/lmnr-ai/lmnr/main/docker-compose-full.yml — services, images, tags, env vars, ports, volumes, caps, depends_on
- https://raw.githubusercontent.com/lmnr-ai/lmnr/main/docker-compose.yml — lightweight variant (comparison)
- https://raw.githubusercontent.com/lmnr-ai/lmnr/main/clickhouse-profiles-config.xml — the bind-mounted profile baked into our image
- https://raw.githubusercontent.com/lmnr-ai/lmnr/main/README.md — self-hosting guidance, LLM provider vars, `POSTGRES_SCHEMA`, telemetry opt-out
- https://raw.githubusercontent.com/lmnr-ai/lmnr/main/CONTRIBUTING.md — compose-file matrix, migrations-at-frontend-boot
- https://raw.githubusercontent.com/lmnr-ai/lmnr/main/app-server/.env.example — `CONSUMER_PORT=8002`, AEAD 64-hex requirement, RO ClickHouse creds = RW creds, optional vars
- https://raw.githubusercontent.com/lmnr-ai/lmnr/main/frontend/.env.local.example — `BETTER_AUTH_*`, auth provider vars, LLM vars
- https://raw.githubusercontent.com/lmnr-ai/lmnr/main/frontend/Dockerfile — Next.js standalone, `HOSTNAME=0.0.0.0`, `PORT` env, migrations copied into image
- https://raw.githubusercontent.com/lmnr-ai/lmnr/main/app-server/src/main.rs — binds `0.0.0.0` on HTTP/gRPC/consumer ports; `/v1/traces` HTTP route
- GitHub code search (lmnr-ai/lmnr): `frontend/lib/auth.ts` (BETTER_AUTH → NEXTAUTH fallback), `frontend/lib/quickwit/indexes/spans_v2.yaml` + `initializeQuickwitIndexes` (indexes created at frontend boot), `app-server/src/env/quickwit.rs`
- https://laminar.sh/docs/self-hosting/docker-compose — SDK self-host config (`baseUrl`/`httpPort`/`grpcPort`), open-auth default, port table
- https://laminar.sh/docs/hosting-options — hosting overview
- GitHub code search (lmnr-ai/lmnr-python): `src/lmnr/sdk/laminar.py` (`force_http`), `sync_client.py` (port defaults to 443)
- GitHub code search (lmnr-ai/lmnr-ts): `initialize-options` / `exporter.ts` (`forceHttp`, `httpPort`), `examples/nextjs/README.md` (upstream example using `forceHttp: true`)
- GHCR tags API (`ghcr.io/v2/lmnr-ai/{app-server,frontend}/tags/list` + manifests) — `latest` exists for both; `latest` digest ≠ `v0.1.13`

Store images:
- https://raw.githubusercontent.com/quickwit-oss/quickwit/v0.8.2/Dockerfile — `ENTRYPOINT ["quickwit"]`, `QW_LISTEN_ADDRESS=0.0.0.0`, `QW_DATA_DIR=/quickwit/qwdata`
- https://raw.githubusercontent.com/quickwit-oss/quickwit/v0.8.2/config/quickwit.yaml — shipped node config
- GitHub code search (quickwit-oss/quickwit): `docs/configuration/node-config.md` — `listen_address` default and `QW_LISTEN_ADDRESS` override
- https://raw.githubusercontent.com/ClickHouse/ClickHouse/master/docker/server/docker_related_config.xml — image listens `::` + `0.0.0.0` with `listen_try`
- https://www.rabbitmq.com/docs/networking — default listeners on all interfaces; dual-stack notes
- Docker Hub tags API (`library/rabbitmq`) — `latest` line is 4.x (4.3.2 at scaffold time)

Railway:
- https://docs.railway.com/networking/private-networking/how-it-works — environments created after 2025-10-16 resolve internal DNS to IPv4 + IPv6; legacy = IPv6-only; private networking unavailable at build time
- https://docs.railway.com/variables/reference — `${{Service.VAR}}` reference syntax, `RAILWAY_PRIVATE_DOMAIN`, `RAILWAY_PUBLIC_DOMAIN`, TCP proxy vars
- https://docs.railway.com/templates/create — `${{secret(length, alphabet)}}` and `randomInt` template functions
- https://station.railway.com/questions/how-to-support-both-grpc-and-http-for-a-5dbb7109 and https://station.railway.com/feedback/http-2-support-on-edge-proxy-50adedfe — edge proxy speaks HTTP/1.1 to upstreams; gRPC needs TCP proxy or private network
