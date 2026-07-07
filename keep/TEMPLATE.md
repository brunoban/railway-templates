# Railway composer spec — Keep

*The build-ready recipe for publishing this template in Railway's composer.
Follow top to bottom; validate with one test deploy before publishing.
Everything below was extracted from Keep v0.54.1 sources and docs on
2026-07-07 — see Sources at the bottom. Items marked **[verify]** need
confirmation during the test deploy.*

## Services (4)

### 1. `Postgres`
- **Source:** Railway database → PostgreSQL (the built-in one)
- Nothing else to configure. Keep supports Postgres as a first-class dialect
  (its Helm chart tests against `postgresql+psycopg2://…`), and the backend
  creates/migrates the schema on boot.

### 2. `keep-websocket-server`  *(create before backend/frontend — they reference its variables)*
- **Source:** Docker image `quay.io/soketi/soketi:1.4-16-debian`
  (exact image+tag from upstream `docker-compose.common.yml`)
- **Variables** (canonical copies live here; backend/frontend reference them):
  - `SOKETI_DEFAULT_APP_ID` = `1`
    (**must stay a numeric string** — see gotcha 2)
  - `SOKETI_DEFAULT_APP_KEY` = `${{secret(32)}}`
  - `SOKETI_DEFAULT_APP_SECRET` = `${{secret(32)}}`
  - `SOKETI_USER_AUTHENTICATION_TIMEOUT` = `3000` (upstream compose value)
  - `SOKETI_DEBUG` = `0` (upstream compose uses `1`; keep prod logs quiet)
- **Networking:** public domain ON, target port **6001**. The browser opens
  `wss://` to this domain directly (see gotcha 3), and the backend publishes
  to it over the private network on 6001.
- Why not Railway's official Soketi template? Self-containment: one composer
  spec, pinned tag, secrets referenced in-project.

### 3. `keep-backend`
- **Source:** Docker image `us-central1-docker.pkg.dev/keephq/keep/keep-api:0.54.1`
  (Google Artifact Registry, public pull; tag `0.54.1` = GitHub release
  v0.54.1. No Docker Hub mirror exists — verified `hub.docker.com` 404s.)
- **Start command:** none — image CMD is gunicorn with 4 uvicorn workers on
  `0.0.0.0:8080`.
- **Variables:**
  - `PORT` = `8080`
  - `DATABASE_CONNECTION_STRING` =
    `postgresql+psycopg2://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/${{Postgres.PGDATABASE}}`
    — composed explicitly so the URL scheme is `postgresql+psycopg2://`, the
    exact form Keep's own Helm chart uses. (`${{Postgres.DATABASE_URL}}` is
    `postgresql://…`, which SQLAlchemy 2 also maps to psycopg2, so it would
    likely work too — but the explicit form removes the doubt.)
  - `AUTH_TYPE` = `DB`
  - `KEEP_JWT_SECRET` = `${{secret(32)}}`
  - `KEEP_DEFAULT_USERNAME` = `keep`
  - `KEEP_DEFAULT_PASSWORD` = `${{secret(16)}}`
  - `KEEP_API_URL` = `https://${{RAILWAY_PUBLIC_DOMAIN}}` (self-reference;
    the base URL Keep hands to providers when registering webhooks)
  - `SECRET_MANAGER_TYPE` = `DB` (provider credentials go to Postgres;
    the default `FILE` writes to `/state`, which is ephemeral on Railway —
    see gotcha 5)
  - `PUSHER_APP_ID` = `${{keep-websocket-server.SOKETI_DEFAULT_APP_ID}}`
  - `PUSHER_APP_KEY` = `${{keep-websocket-server.SOKETI_DEFAULT_APP_KEY}}`
  - `PUSHER_APP_SECRET` = `${{keep-websocket-server.SOKETI_DEFAULT_APP_SECRET}}`
  - `PUSHER_HOST` = `${{keep-websocket-server.RAILWAY_PRIVATE_DOMAIN}}`
  - `PUSHER_PORT` = `6001`
  - **Do NOT set `PUSHER_USE_SSL` at all** — see gotcha 1.
  - `EE_ENABLED` = `false` (explicit; also the code default)
  - `SENTRY_DISABLED` = `true`, `POSTHOG_DISABLED` = `true` (images bake in
    Keep's own telemetry endpoints; opt the deployment out)
  - `PROMETHEUS_MULTIPROC_DIR` = `/tmp/prometheus`, `KEEP_METRICS` = `true`
    (upstream compose values)
  - *(optional but recommended)* `KEEP_DEFAULT_API_KEYS` =
    `railway-template:webhook:${{secret(32)}}` — pre-provisions an
    ingestion-scoped API key so the post-deploy test alert needs no UI steps.
    Format `name:role:secret` per upstream config docs. **[verify]** the
    `webhook` role name at test deploy.
- **Networking:** public domain ON, target port 8080. Public because external
  monitoring tools POST alerts here and `KEEP_API_URL` must be reachable from
  their side. (The UI itself would survive without it — browser calls go
  through the frontend's `/backend` proxy.)
- **Healthcheck:** path `/healthcheck` (unauthenticated FastAPI route).
- **Sizing:** 1 GB RAM recommended (gunicorn 4 workers + scheduler + consumer
  in-process; `SCHEDULER`/`CONSUMER` default `true` — no separate worker or
  Redis service needed, matching upstream compose which ships neither).

### 4. `keep-frontend`
- **Source:** Docker image `us-central1-docker.pkg.dev/keephq/keep/keep-ui:0.54.1`
  (same registry/tag scheme as the backend — keep both tags in lockstep)
- **Start command:** none — image entrypoint execs `node server.js`
  (Next.js standalone) on port 3000.
- **Variables:**
  - `PORT` = `3000`
  - `AUTH_TYPE` = `DB` (must match the backend)
  - `NEXTAUTH_SECRET` = `${{secret(32)}}` (independent of `KEEP_JWT_SECRET`;
    they do not need to match — the frontend stores the backend-issued token
    inside its own encrypted session)
  - `NEXTAUTH_URL` = `https://${{RAILWAY_PUBLIC_DOMAIN}}` (self-reference)
  - `API_URL` = `http://${{keep-backend.RAILWAY_PRIVATE_DOMAIN}}:8080` —
    server-side only: SSR calls and the `/backend/*` middleware rewrite both
    use it over the private network.
  - `API_URL_CLIENT` — **leave unset.** The browser then uses the relative
    `/backend` path (frontend middleware rewrites it to `API_URL`), which
    sidesteps CORS entirely. This is the upstream default
    (`getApiUrlFromConfig` falls back to `/backend`).
  - `PUSHER_HOST` = `${{keep-websocket-server.RAILWAY_PUBLIC_DOMAIN}}` —
    the **public** Soketi domain, bare hostname (no scheme):
    `usePusher.ts` passes it straight to pusher-js as `wsHost`.
  - `PUSHER_PORT` = `443` — the browser connects through Railway's TLS edge;
    pusher-js sets `forceTLS` automatically because the page is https.
  - `PUSHER_APP_KEY` = `${{keep-websocket-server.SOKETI_DEFAULT_APP_KEY}}`
    (the frontend never sees the app secret — channel auth is delegated to
    the backend's `/pusher/auth` via the `/backend` proxy)
  - `SENTRY_DISABLED` = `true`, `POSTHOG_DISABLED` = `true`
- **Networking:** public domain ON (this is the UI), target port 3000.
- **Healthcheck:** path `/api/healthcheck` (excluded from auth redirect in
  `middleware.ts`).
- **Sizing:** 512 MB RAM.

## Gotchas (check these during the test deploy)

1. **`PUSHER_USE_SSL` is string-truthy — never set it to `"false"`.**
   Backend code (`keep/api/core/dependencies.py`):
   ```python
   ssl=False if os.environ.get("PUSHER_USE_SSL", False) is False else True
   ```
   Any set value — including the string `"false"` — enables SSL. Plaintext
   over the private network requires the variable to be *absent*. Only set it
   (to anything) if you rewire the backend to Soketi's public domain.
2. **`PUSHER_APP_ID` must be a numeric string.** The backend catches
   `ValueError` from the Pusher client and *silently disables* real-time
   push if the app ID isn't numeric. Do not "improve" it to a generated
   alphanumeric secret. The ID is not sensitive; `1` (upstream's value) is fine.
3. **Browser → Soketi is a direct `wss://` connection.** The frontend hands
   `PUSHER_HOST`/`PUSHER_PORT` to the browser; there is no server-side relay.
   Hence Soketi's public domain + frontend `PUSHER_PORT=443`. **[verify]**
   at test deploy that Railway's edge upgrades the websocket on the Soketi
   domain (Network tab → `wss://<soketi-domain>/app/<key>` → 101).
4. **Backend → Soketi rides the private network (IPv4/IPv6 note).** Soketi
   binds `0.0.0.0` (IPv4). Railway environments created after 2025-10-16
   resolve `*.railway.internal` to IPv4 *and* IPv6, so this works on any
   fresh template deploy; only pre-2025 legacy environments are IPv6-only.
   **[verify]** at test deploy: trigger an alert and watch Soketi logs for
   the backend's POST. Fallback if it can't connect: set backend
   `PUSHER_HOST` to the Soketi *public* domain, `PUSHER_PORT=443`,
   `PUSHER_USE_SSL=true`.
5. **Secrets in DB, not `/state`.** Upstream compose uses
   `SECRET_MANAGER_TYPE=FILE` with a bind-mounted `./state` volume. Railway
   containers have ephemeral filesystems, so this template uses `DB`
   (a supported enum in `keep/secretmanager/secretmanagerfactory.py`).
   Alternative: keep `FILE` + `SECRET_MANAGER_DIRECTORY=/state` and mount a
   Railway volume at `/state` on the backend — not the default here because
   volumes pin the service to a single replica.
6. **Auth default is `DB`, not upstream's `NO_AUTH`.** A public template URL
   with `NO_AUTH` is an open alert console and open API. `DB` auth matches
   upstream's `docker-compose-with-auth.yml`. The default user (`keep` +
   generated `KEEP_DEFAULT_PASSWORD`) is seeded **only on first boot**;
   changing the env var later does nothing unless
   `KEEP_FORCE_RESET_DEFAULT_PASSWORD=true` is set for one deploy.
7. **EE stays off.** The image contains the proprietary `ee/` directory, but
   `keep/api/utils/import_ee.py` only imports it when `EE_ENABLED=true`
   (default `false`; the template pins it to `false` explicitly). The
   deployed product is the MIT core. Marketplace copy must say so.
8. **Boot order / Postgres readiness.** The backend crash-loops briefly if it
   wins the race against Postgres; Railway restarts it and it settles, then
   runs `migrate_db()` and seeds the tenant + default user. Same story as the
   Dagster template — do not add init hacks.
9. **Prod builds strip `console.log`** (`removeConsole` in `next.config.js`),
   so the `usePusher` debug logs are absent — verify the websocket via the
   Network tab, not the console.
10. **Renames break references.** All cross-service wiring uses
    `${{keep-websocket-server.*}}` / `${{keep-backend.*}}` / `${{Postgres.*}}`
    reference variables; renaming a service in the composer means fixing
    every reference to it.

## Post-deploy verification checklist

- [ ] Frontend public URL redirects to `/signin`; login with `keep` +
      generated `KEEP_DEFAULT_PASSWORD` succeeds
- [ ] Backend public URL `/healthcheck` returns 200; `/` returns the API
      banner JSON with `"version": "0.54.1"`
- [ ] Websocket: DevTools → Network → WS shows an open (101) connection to
      `wss://<soketi-domain>/app/<PUSHER_APP_KEY>` after login
- [ ] Send a test alert via API (with the pre-provisioned key, or one created
      in Settings → API Keys):
      ```
      curl -X POST "https://<keep-backend-domain>/alerts/event" \
        -H "X-API-KEY: <key>" -H "Content-Type: application/json" \
        -d '{"name":"template-smoke-test","status":"firing","severity":"critical","service":"railway-template"}'
      ```
      **[verify]** exact payload shape against the deployed `/docs` OpenAPI
      page — then confirm the alert appears in the feed *without a manual
      page refresh* (that also proves backend → Soketi → browser end-to-end)
- [ ] Create a trivial workflow (or rely on provisioned examples) and confirm
      the scheduler ticks it (backend logs: "Starting the scheduler")
- [ ] Redeploy the backend and confirm alerts + provider secrets survive
      (proves Postgres-backed state and `SECRET_MANAGER_TYPE=DB`)

## Marketplace listing

- **Name:** Keep
- **Category:** Monitoring / Observability (or closest available)
- **Overview (draft):** "The open-source AIOps and alert-management platform,
  deployed the way upstream runs it: Next.js UI, FastAPI backend with
  scheduler and consumer, Soketi websocket server for real-time updates, and
  Postgres for everything durable. Aggregate and deduplicate alerts from
  Prometheus, Grafana, Datadog, CloudWatch and 100+ other tools, enrich and
  correlate them, and automate responses with workflows. Ships with DB
  authentication on and generated secrets — no open consoles. Deploys the
  MIT-licensed core; enterprise (`ee/`) features are disabled."
- Enable the kickback option when publishing; support requests come through
  the Template Queue.

## Maintenance

- Watch [keephq/keep releases](https://github.com/keephq/keep/releases);
  bump `keep-api` and `keep-ui` tags **together** (they are released in
  lockstep — v0.54.1 today). DB migrations run automatically on backend boot.
- Soketi `1.4-16-debian` moves rarely; check quay.io occasionally.
- Keep's env surface churns (the `API_URL`/`API_URL_CLIENT` split and the
  `/backend` proxy are recent-generation behavior). On a failed upgrade,
  re-diff `docker-compose.common.yml` and `getConfig.ts` first.
- If deploy success rate drops on the template dashboard: check Artifact
  Registry availability (`us-central1-docker.pkg.dev` is the only image
  source — there is no Docker Hub fallback), then upstream env renames.

## Sources (fetched 2026-07-07)

- https://raw.githubusercontent.com/keephq/keep/main/docker-compose.yml — service set, image names, `AUTH_TYPE`, `API_URL`
- https://raw.githubusercontent.com/keephq/keep/main/docker-compose.common.yml — ports, `PUSHER_*` for both frontend (browser-facing) and backend (internal), Soketi image+tag+env, `SECRET_MANAGER_TYPE`
- https://raw.githubusercontent.com/keephq/keep/main/docker-compose-with-auth.yml — DB-auth variable set (`KEEP_JWT_SECRET`, `NEXTAUTH_SECRET`, default user)
- https://docs.keephq.dev/deployment/configuration — full env reference (AUTH_TYPE values, SECRET_MANAGER_TYPE values, Redis/ARQ, `KEEP_DEFAULT_API_KEYS` format)
- https://docs.keephq.dev/deployment/docker — compose-based install flow
- keephq/keep **v0.54.1** source (raw.githubusercontent.com):
  `keep/api/api.py` (SCHEDULER/CONSUMER defaults, CORS, KEEP_API_URL default),
  `keep/api/config.py` (boot-time `migrate_db()`, tenant/user seeding),
  `keep/api/consts.py` (`REDIS` default false, ARQ pools),
  `keep/api/core/dependencies.py` (Pusher client, `PUSHER_USE_SSL` quirk, numeric APP_ID),
  `keep/api/core/db_utils.py` (connection-string handling, Postgres dialect),
  `keep/api/utils/import_ee.py` (`EE_ENABLED` gate), `ee/LICENSE`,
  `keep/secretmanager/secretmanagerfactory.py` (`DB` secret manager),
  `keep/entrypoint.sh` (ARQ workers co-located when `REDIS=true`),
  `docker/Dockerfile.api`, `docker/Dockerfile.ui` (ports, CMDs, baked telemetry),
  `keep-ui/utils/hooks/usePusher.ts` (browser connects to Soketi directly, forceTLS),
  `keep-ui/shared/lib/server/getConfig.ts` + `keep-ui/utils/apiUrl.ts` (API_URL vs API_URL_CLIENT),
  `keep-ui/shared/lib/getApiUrlFromConfig.ts` (`/backend` default),
  `keep-ui/middleware.ts` (`/backend/*` rewrite, healthcheck exclusions),
  `keep-ui/utils/authenticationType.ts` (`AUTH_TYPE=DB` enum value),
  `keep-ui/entrypoint.sh` (NEXTAUTH_SECRET warning)
- https://github.com/keephq/keep/releases/latest — v0.54.1
- Artifact Registry tag lists (`us-central1-docker.pkg.dev/v2/keephq/keep/{keep-api,keep-ui}/tags/list`) — `0.54.1` + `latest` exist for both; Docker Hub `keephq/keep-{api,ui}` do **not** exist
- https://raw.githubusercontent.com/keephq/helm-charts/main/local_test_postgresql.sh — upstream `postgresql+psycopg2://` connection-string form
- https://raw.githubusercontent.com/soketi/soketi/master/src/server.ts — default bind `0.0.0.0`
- https://docs.railway.com/networking/private-networking/how-it-works — IPv4+IPv6 on new environments, IPv6-only on legacy
- https://docs.railway.com/guides/create — `${{secret(32)}}` template function syntax
