# Laminar on Railway

Deploy [Laminar](https://github.com/lmnr-ai/lmnr) (lmnr) — the open-source
observability platform for LLM apps and AI agents: OpenTelemetry-native
tracing, evals, datasets, full-text search over spans, and dashboards. This
template mirrors upstream's `docker-compose-full.yml`, the compose file the
Laminar team recommends for production self-hosting — not the lightweight
quickstart stack.

```
   browser ── HTTPS ──►┌──────────────────────┐
                       │       frontend       │  Next.js UI (public :5667)
                       │ runs PG + ClickHouse │
                       │ migrations & creates │
                       │ Quickwit idx at boot │
                       └──┬────┬────┬────┬────┘
                          │    │    │    │ BACKEND_URL :8000 / BACKEND_RT_URL :8002
 SDKs / OTLP ─ HTTPS ─►┌──┼────┼────┼────▼────┐
 (forceHttp)           │  │    │  app-server  │  Rust ingest + API (public :8000,
                       └──┼────┼──┬───┬───┬───┘  gRPC :8001 + realtime :8002 private)
                          │    │  │   │   │
                 ┌────────▼┐ ┌─▼──▼─┐ ┌▼───▼───┐ ┌─────────▼─┐
                 │Postgres │ │Click-│ │Quickwit│ │ RabbitMQ  │
                 │metadata,│ │house │ │ span   │ │ span      │
                 │users    │ │spans │ │ search │ │ queue     │
                 └─────────┘ └──────┘ └────────┘ └───────────┘
```

Six services: the two Laminar images (`ghcr.io/lmnr-ai/frontend`,
`ghcr.io/lmnr-ai/app-server`) plus four stores — Postgres (traces metadata,
users, projects), ClickHouse (span analytics), Quickwit (full-text span
search), RabbitMQ (ingestion queue). Postgres, ClickHouse, and Quickwit are
stateful and get volumes; RabbitMQ is a transient queue and — matching
upstream's compose — runs without one.

ClickHouse uses a thin custom image
(`ghcr.io/brunoban/railway-laminar-clickhouse`, built from this directory by
CI): upstream bind-mounts a one-setting profile XML into the container, Railway
has no bind mounts, so the image bakes that file in. Base image and tag are
upstream's own (`clickhouse/clickhouse-server:26.5`).

## Sending traces from your app

The Laminar UI is only half the product — your app's SDK ships spans to the
**app-server**, which this template exposes on its own public domain. Railway's
HTTPS edge does not carry gRPC end-to-end, so configure the SDK to export over
HTTP (supported and shown in upstream's own Next.js examples):

```python
# Python (pip install 'lmnr[all]')
from lmnr import Laminar
Laminar.initialize(
    project_api_key="<key from your project settings>",
    base_url="https://<your-app-server-domain>",  # no port; 443 is the default
    force_http=True,
)
```

```typescript
// TypeScript (npm add @lmnr-ai/lmnr)
import { Laminar } from '@lmnr-ai/lmnr';
Laminar.initialize({
  projectApiKey: "<key>",
  baseUrl: "https://<your-app-server-domain>",
  httpPort: 443,
  forceHttp: true,
});
```

Create the project and API key in the UI first (self-hosted default: any user
can sign up and sign in — put OAuth in front of it before exposing to a team,
see below).

## Environment variables

Wired by the template (you shouldn't need to touch these):

| Variable | Service(s) | Value | Purpose |
|---|---|---|---|
| `DATABASE_URL` | app-server, frontend | `${{Postgres.DATABASE_URL}}` | Traces metadata, users, projects |
| `RABBITMQ_URL` | app-server | built from rabbitmq service creds | Span ingestion queue |
| `CLICKHOUSE_URL` / `_USER` / `_PASSWORD` | app-server, frontend | clickhouse service refs | Span analytics store |
| `CLICKHOUSE_RO_USER` / `_RO_PASSWORD` | app-server | same as read-write user | Upstream self-host default (no separate RO user) |
| `QUICKWIT_SEARCH_URL` / `QUICKWIT_INGEST_URL` | app-server (frontend: search only) | quickwit service, :7280 / :7281 | Full-text span search |
| `QUICKWIT_SPANS_INDEX_ID` | app-server | `spans_v2` | Index id; frontend creates it at boot |
| `SHARED_SECRET_TOKEN` | app-server, frontend | generated, shared | Internal frontend ↔ app-server auth |
| `AEAD_SECRET_KEY` | app-server, frontend | generated 64-hex-char (32 bytes), shared | Payload encryption — must match on both |
| `ENVIRONMENT` | app-server, frontend | `FULL` | Enables the RabbitMQ-backed pipeline |
| `BETTER_AUTH_URL` / `BETTER_AUTH_SECRET` | frontend | public URL / generated | Auth (Better Auth; `NEXTAUTH_*` are legacy aliases) |
| `NEXT_PUBLIC_URL` | frontend | public URL | Browser-side base URL |
| `BACKEND_URL` / `BACKEND_RT_URL` | frontend | app-server private :8000 / :8002 | Server-side API + realtime trace streaming |

Yours to set (all optional):

| Variable | Service | Purpose |
|---|---|---|
| `LLM_PROVIDER` | frontend | `openai` \| `gemini` \| `bedrock` — enables chat-with-trace, SQL-with-AI |
| `LLM_API_KEY`, `LLM_BASE_URL` | frontend | Key for openai/gemini; base URL for OpenAI-compatible gateways |
| `LLM_MODEL_SMALL` / `_MEDIUM` / `_LARGE` | frontend | Model overrides; per-provider defaults apply |
| `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | frontend | Credentials for `LLM_PROVIDER=bedrock` |
| `AUTH_GITHUB_ID` / `AUTH_GITHUB_SECRET` (also Google/Okta/Keycloak) | frontend | OAuth sign-in instead of open email auth |
| `LAMINAR_TELEMETRY_DISABLED` | app-server, frontend | `true` opts out of anonymized usage telemetry |

## Sizing

Upstream publishes no per-service sizing; these are working estimates for a
small team — scale ClickHouse first as trace volume grows:

- **ClickHouse** — the workhorse; every span lands here. Start at 2GB RAM,
  expect to grow. Give its volume the most room.
- **Quickwit** — 1–2GB; indexes span text for search.
- **app-server** — 512MB–1GB; Rust, but it runs many queue-consumer workers.
- **frontend** — ~512MB; also runs all migrations at boot.
- **Postgres / RabbitMQ** — ~512MB each at this scale.

## Upgrading

Upstream's compose deliberately tracks the `latest` tag for both Laminar
images (it moves ahead of the newest versioned release). To upgrade, redeploy
**frontend and app-server together** — the frontend applies Postgres and
ClickHouse migrations at startup, and the pair are built in lockstep from the
same repo. Don't pin one and float the other. ClickHouse (26.5) and Quickwit
(v0.8.2) stay on upstream's pinned tags; bump them only when
`docker-compose-full.yml` does.
