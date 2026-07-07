# Keep on Railway

Deploy [Keep](https://github.com/keephq/keep) — the open-source alert
management and AIOps platform — as the same multi-service stack upstream ships
in its own docker-compose: aggregation and deduplication of alerts from any
monitoring tool (Prometheus, Grafana, Datadog, CloudWatch, …), enrichment,
correlation rules, workflow automation, and bi-directional integrations.

```
                        browser
               ┌───────────┴────────────────────────┐
               │ https                              │ wss (direct)
               ▼                                    ▼
  ┌────────────────────────┐        ┌───────────────────────────┐
  │     keep-frontend      │        │   keep-websocket-server   │
  │ Next.js UI  (public)   │        │ Soketi :6001   (public)   │
  │ proxies /backend/* ────┼──┐     └─────────────▲─────────────┘
  └────────────────────────┘  │                   │ private :6001
               ┌──────────────┘                   │ (backend pushes events)
               ▼                                  │
  ┌────────────────────────┐                      │
  │      keep-backend      │──────────────────────┘
  │ FastAPI :8080 (public) │◄─── webhooks from your monitoring tools
  │ + scheduler + consumer │
  └───────────┬────────────┘
              ▼
       ┌────────────┐
       │  Postgres  │  alerts · incidents · workflows · provider secrets
       └────────────┘
```

Four services, all official upstream images — no custom builds:

| Service | Image | Role |
|---|---|---|
| `keep-frontend` | `us-central1-docker.pkg.dev/keephq/keep/keep-ui:0.54.1` | UI; also proxies browser API calls to the backend at `/backend` |
| `keep-backend` | `us-central1-docker.pkg.dev/keephq/keep/keep-api:0.54.1` | REST API, workflow scheduler and event consumer (both run in-process) |
| `keep-websocket-server` | `quay.io/soketi/soketi:1.4-16-debian` | Pusher-protocol websocket server for real-time UI updates |
| `Postgres` | Railway PostgreSQL | All state, including provider secrets (`SECRET_MANAGER_TYPE=DB`) |

The containers are stateless — everything durable lives in Postgres — so
redeploys and image bumps are safe.

## OSS core only — EE stays off

Keep's repository is MIT-licensed except the `ee/` directory, which is under a
proprietary enterprise license. The `ee/` code ships inside the official image
but is only imported when `EE_ENABLED=true`
([`keep/api/utils/import_ee.py`](https://github.com/keephq/keep/blob/v0.54.1/keep/api/utils/import_ee.py)
defaults it to `false`). This template pins `EE_ENABLED=false` explicitly: you
deploy the MIT core only. If you hold an enterprise license, flip the flag
yourself — nothing else in the template changes.

## Authentication

The template deploys with `AUTH_TYPE=DB` (username/password stored in
Postgres), mirroring upstream's `docker-compose-with-auth.yml` — **not**
`NO_AUTH`, which upstream defaults to but which would leave a public Railway
URL wide open. Log in as user **`keep`** with the generated
`KEEP_DEFAULT_PASSWORD` (visible in `keep-backend`'s service variables).
Passwords are only seeded on first boot; to rotate via env later, set
`KEEP_FORCE_RESET_DEFAULT_PASSWORD=true` for one deploy.

## Environment variables

Wired by the template — you shouldn't need to touch these on day one:

| Variable | Service(s) | Wired to | Purpose |
|---|---|---|---|
| `DATABASE_CONNECTION_STRING` | backend | Railway Postgres (`postgresql+psycopg2://…`) | All Keep state; schema auto-migrates on boot |
| `AUTH_TYPE` | frontend, backend | `DB` | Username/password auth (see above) |
| `KEEP_JWT_SECRET` | backend | generated | Signs API access tokens |
| `NEXTAUTH_SECRET` | frontend | generated | Encrypts UI sessions (independent of the JWT secret) |
| `NEXTAUTH_URL` | frontend | frontend public URL | NextAuth callback base |
| `KEEP_DEFAULT_USERNAME` / `KEEP_DEFAULT_PASSWORD` | backend | `keep` / generated | First-boot admin user |
| `API_URL` | frontend | backend private URL | Server-side API calls (browser traffic goes through the frontend's `/backend` proxy — `API_URL_CLIENT` stays unset) |
| `KEEP_API_URL` | backend | backend public URL | Base URL Keep advertises for provider webhooks |
| `PUSHER_APP_ID/KEY/SECRET` | backend ↔ soketi | shared, key/secret generated | Pusher-protocol credentials (`APP_ID` must stay numeric) |
| `PUSHER_HOST` / `PUSHER_PORT` | backend | soketi private domain / `6001` | Backend → Soketi event publishing |
| `PUSHER_HOST` / `PUSHER_PORT` | frontend | soketi **public** domain / `443` | The browser connects to Soketi directly over `wss` |
| `SECRET_MANAGER_TYPE` | backend | `DB` | Provider credentials in Postgres — the upstream default (`FILE`, `/state`) would evaporate on redeploy |
| `EE_ENABLED` | backend | `false` | Enterprise code stays unloaded |
| `SENTRY_DISABLED` / `POSTHOG_DISABLED` | frontend, backend | `true` | The images bake in Keep's own Sentry DSN and PostHog key; the template opts your deployment out |

Useful knobs you may set later (see the
[upstream configuration reference](https://docs.keephq.dev/deployment/configuration)):
`OPENAI_API_KEY` (AI features), `KEEP_DEFAULT_API_KEYS`
(pre-provision API keys as `name:role:secret`), `PROVISION_RESOURCES`,
`KEEP_USE_LIMITER`, `LOG_LEVEL`.

## Scaling: Redis + ARQ workers (optional, off by default)

Out of the box the backend runs its scheduler and consumer in-process
(`SCHEDULER=true`, `CONSUMER=true` are upstream defaults) with no queue —
exactly like upstream's docker-compose, which ships no Redis at all. For
higher alert volume, add a Railway Redis service and set on `keep-backend`:
`REDIS=true`, `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` (reference the
Redis service's variables). The image's entrypoint then starts ARQ background
workers *inside the same container* alongside the API — no extra Railway
service required.

## Sizing

- **keep-backend** is the heavy one: gunicorn with 4 uvicorn workers plus
  scheduler/consumer. Start at 1 GB RAM; raise with workflow volume.
- **keep-frontend** is a standalone Next.js server — ~512 MB is comfortable.
- **keep-websocket-server** (Soketi) idles tiny — 256 MB is plenty.
- Postgres: Railway defaults are fine to start; alert history is the growth
  driver.

## Upgrading

Bump both Keep image tags (`keep-ui` and `keep-api`) to the same version and
redeploy — keep them in lockstep. The backend runs its own DB migrations on
boot (`migrate_db()` in `keep/api/config.py`), so there is no separate
migration step. Soketi is protocol-stable; upgrade it independently and
rarely. Pin exact versions (this template ships `0.54.1`) rather than
`latest`, so upgrades are deliberate.
